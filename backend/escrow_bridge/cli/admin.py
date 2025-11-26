import click
from escrow_bridge import network_func, get_exchange_rate, erc20_abi, ZERO_ADDRESS, SUPPORTED_NETWORKS, get_decimals
from escrow_bridge.cli import (
    console, print_status, print_panel, progress_bar, print_json, print_table, symbol_map
)
import os
import json
import time

MAX_256 = 2**256 - 1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Go up from escrow_bridge/cli to backend
BACKEND_DIR = os.path.join(BASE_DIR, "..", "..")
# Go up from escrow_bridge/cli to project root, then to contracts
CONTRACTS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "contracts")

CONFIG_PATH = os.path.join(BACKEND_DIR, 'chainsettle_config.json')
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

# Using EscrowBridge (USDC version) for BlockDAG
escrow_bridge_artifact_path = os.path.join(CONTRACTS_DIR, "out", "EscrowBridge.sol", "EscrowBridge.json")
bdag_address_path = os.path.join(CONTRACTS_DIR, "deployments", "blockdag-escrow-bridge.json")

with open(bdag_address_path, 'r') as f:
    ESCROW_BRIDGE_ADDRESS_BDAG = json.load(f)['deployedTo']

with open(escrow_bridge_artifact_path, 'r') as f:
    escrow_bridge_abi = json.load(f)['abi']

# EscrowBridge (USDC) on BlockDAG Testnet only
escrow_bridge_config = {
    "blockdag-testnet": {
        "address": ESCROW_BRIDGE_ADDRESS_BDAG,
        "abi": escrow_bridge_abi
    },
}

@click.group()
def cli():
    """Escrow Bridge Admin CLI"""
    pass

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of USDC to top up the EscrowBridge contract with (normalized).")
@click.option("--network", default="blockdag-testnet", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
def fund_escrow(amount, network):
    """Fund the EscrowBridge contract with USDC tokens."""
    print_panel("Fund Escrow Bridge", tone="info")

    REGISTRY_ADDRESS = config["blockdag"]['registry_addresses']["paypal"]

    with progress_bar("Connecting to network...") as progress:
        task = progress.add_task("Setting up...", total=None)
        w3, account = network_func(network=network)

    print(f'account address: {account.address}')

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)

    # Display info
    rows = [
        ("EOA", account.address[:20] + "..."),
        ("Contract", contract_address[:20] + "..."),
        ("Network", network),
    ]
    print_table(["Field", "Value"], rows, title="Connection Info")

    onchain_reg_address = bridge.functions.settlementRegistry().call()
    print_status(f"Registry address: {onchain_reg_address[:20]}...", level="info")

    if REGISTRY_ADDRESS.lower() != onchain_reg_address.lower():
        print_status(f"Registry mismatch! Expected: {REGISTRY_ADDRESS[:20]}...", level="error")
        raise click.ClickException("Registry address mismatch.")

    # Check limits
    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()

    # Fetch token details
    try:
        usdc_address = bridge.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)
        token_decimals = erc20.functions.decimals().call()
        symbol = "USDC"
        token_address = usdc_address
    except Exception as e:
        print_status(f"Error fetching token details: {e}", level="warn")
        token_decimals = 18
        symbol = "BDAG"
        token_address = ZERO_ADDRESS
        erc20 = None

    print(f'token_address: {token_address}, symbol: {symbol}, decimals: {token_decimals}')

    fee = bridge.functions.fee().call()

    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)

    # Display token info
    rows = [
        ("Token", f"{token_address[:20]}... ({symbol})"),
        ("Decimals", str(token_decimals)),
        ("Fee", f"{fee / 10000:.2f}%"),
        ("Min", f"{min_human:.6f} {symbol}"),
        ("Max", f"{max_human:.6f} {symbol}"),
    ]
    print_table(["Field", "Value"], rows, title="Token Info")

    if amount < min_human or amount > max_human:
        print_status(f"Amount {amount} {symbol} out of bounds.", level="error")
        raise click.ClickException("Amount out of bounds.")

    amount_raw = int(amount * (10 ** token_decimals))
    top_up = amount_raw
    print_status(f"Funding with {top_up / (10**token_decimals):.6f} {symbol}", level="info")

    # Check EOA balance
    owner_raw_balance = erc20.functions.balanceOf(account.address).call() if erc20 else w3.eth.get_balance(account.address)
    owner_human_balance = owner_raw_balance / (10 ** token_decimals)
    print_status(f"EOA balance: {owner_human_balance:.6f} {symbol}", level="info")

    if owner_raw_balance < top_up:
        print_status(f"Insufficient {symbol} balance.", level="error")
        raise click.ClickException("Insufficient balance.")

    base_nonce = w3.eth.get_transaction_count(account.address)

    if token_address != ZERO_ADDRESS:
        approved_amount = erc20.functions.allowance(account.address, contract_address).call()
        if approved_amount < top_up:
            print_status("Approving token transfer...", level="info")

            with progress_bar("Approving...") as progress:
                task = progress.add_task("Sending approval...", total=None)
                approve_tx = erc20.functions.approve(contract_address, top_up).build_transaction({
                    "from": account.address,
                    "nonce": base_nonce,
                })
                gas_est = w3.eth.estimate_gas(approve_tx)
                latest_block = w3.eth.get_block("latest")
                base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
                priority_fee = w3.to_wei(2, "gwei")
                max_fee = base_fee + priority_fee

                approve_tx.update({
                    "gas": int(gas_est * 1.5),
                    "maxPriorityFeePerGas": priority_fee,
                    "maxFeePerGas": max_fee,
                    "type": 2
                })
                signed_approve = account.sign_transaction(approve_tx)
                h_approve = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
                receipt_approve = w3.eth.wait_for_transaction_receipt(h_approve)

            if receipt_approve.status != 1:
                print_status("ERC20.approve(...) reverted", level="error")
                raise click.ClickException("Approval failed.")

            print_status(f"Approved {symbol_map['arrow']} Tx: {h_approve.hex()[:20]}...", level="success")

            time.sleep(5)

            current_allowance = erc20.functions.allowance(account.address, contract_address).call()
            if current_allowance < top_up:
                print_status("Allowance was not set correctly.", level="error")
                raise click.ClickException("Allowance error.")
        else:
            print_status(f"Allowance already sufficient: {approved_amount}", level="success")
    else:
        print_status("No ERC20 token to approve (native token).", level="info")

    if erc20:
        print_status("Funding EscrowBridge with ERC20...", level="info")

        with progress_bar("Funding...") as progress:
            task = progress.add_task("Submitting transaction...", total=None)
            fund_tx = bridge.functions.fundEscrow(top_up).build_transaction({
                "from": account.address,
                "nonce": base_nonce + 1,
            })
            gas_est = w3.eth.estimate_gas(fund_tx)
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
            priority_fee = w3.to_wei(2, "gwei")
            max_fee = base_fee + priority_fee

            fund_tx.update({
                "gas": int(gas_est * 1.5),
                "maxPriorityFeePerGas": priority_fee,
                "maxFeePerGas": max_fee,
                "type": 2
            })
            signed_fund = account.sign_transaction(fund_tx)
            h_fund = w3.eth.send_raw_transaction(signed_fund.raw_transaction)
            receipt_fund = w3.eth.wait_for_transaction_receipt(h_fund)

        if receipt_fund.status != 1:
            print_status("EscrowBridge.fundEscrow(...) reverted", level="error")
            raise click.ClickException("Fund failed.")

        print_status(f"Funded {top_up / (10**token_decimals):.6f} {symbol} {symbol_map['arrow']} Tx: {h_fund.hex()[:20]}...", level="success")
    else:
        print_status("Funding EscrowBridge with native token...", level="info")

        with progress_bar("Funding...") as progress:
            task = progress.add_task("Submitting transaction...", total=None)
            base_nonce = w3.eth.get_transaction_count(account.address, "pending")
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
            priority_fee = w3.to_wei(2, "gwei")
            max_fee = base_fee + priority_fee

            tx = {
                "from": account.address,
                "to": contract_address,
                "value": top_up,
                "maxPriorityFeePerGas": priority_fee,
                "maxFeePerGas": max_fee,
                "nonce": base_nonce,
                "chainId": w3.eth.chain_id
            }

            try:
                gas_est = w3.eth.estimate_gas(tx)
            except Exception as e:
                print_status(f"Failed to estimate gas: {e}", level="warn")
                gas_est = 200000

            tx['gas'] = gas_est

            signed_tx = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        print_status(f"Funded {symbol_map['arrow']} Tx: {tx_hash.hex()[:20]}...", level="success")
        print_status(f"Confirmed in block {receipt.blockNumber}", level="info")

    time.sleep(10)

    # Verify final balance
    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    bridge_human_balance = bridge_raw_balance / (10 ** token_decimals)
    print_status(f"Bridge balance: {bridge_human_balance:.6f} {symbol}", level="success")

@click.command()
@click.option("--network", default="blockdag-testnet", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
def check_exchange_rate(network):
    """Check the current exchange rate on the bridge."""
    print_panel("Check Exchange Rate", tone="info")

    with progress_bar("Connecting...") as progress:
        task = progress.add_task("Fetching rate...", total=None)
        w3, account = network_func(network=network)

        contract_address = escrow_bridge_config[network]['address']
        bridge_abi = escrow_bridge_config[network]['abi']

        bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
        current_rate = get_exchange_rate(bridge)

    print_status(f"Current exchange rate: {current_rate:.6f} USD", level="success")

@click.command()
@click.option("--network", default="blockdag-testnet", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
@click.option("--exchange-rate", type=float, help="New exchange rate in USD.", required=True)
def update_exchange_rate(network, exchange_rate):
    """Update the exchange rate on the bridge contract."""
    print_panel("Update Exchange Rate", tone="info")

    with progress_bar("Connecting...") as progress:
        task = progress.add_task("Setting up...", total=None)
        w3, account = network_func(network=network)

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)

    decimals = get_decimals(w3, bridge)

    raw_exchange_rate = int(exchange_rate * (10 ** decimals))

    current_rate = get_exchange_rate(bridge)
    print_status(f"Current rate: {current_rate:.6f} USD", level="info")
    print_status(f"New rate: {exchange_rate:.6f} USD", level="info")

    with progress_bar("Updating...") as progress:
        task = progress.add_task("Submitting transaction...", total=None)
        update_tx = bridge.functions.updateExchangeRate(raw_exchange_rate).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        })
        gas_est = w3.eth.estimate_gas(update_tx)
        latest_block = w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
        priority_fee = w3.to_wei(2, "gwei")
        max_fee = base_fee + priority_fee

        update_tx.update({
            "gas": int(gas_est * 1.5),
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2
        })
        signed_update = account.sign_transaction(update_tx)
        h_update = w3.eth.send_raw_transaction(signed_update.raw_transaction)
        receipt_update = w3.eth.wait_for_transaction_receipt(h_update)

    if receipt_update.status != 1:
        print_status("Bridge.updateExchangeRate(...) reverted", level="error")
        raise click.ClickException("Update failed.")

    print_status(f"Updated {symbol_map['arrow']} Tx: 0x{h_update.hex()[:16]}...", level="success")

    time.sleep(2)

    new_rate = get_exchange_rate(bridge)
    print_status(f"Verified new rate: {new_rate:.6f} USD", level="success")

cli.add_command(fund_escrow)
cli.add_command(check_exchange_rate)
cli.add_command(update_exchange_rate)

if __name__ == "__main__":
    cli()
