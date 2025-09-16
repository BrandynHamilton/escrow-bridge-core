import click
from escrow_bridge import network_func, get_exchange_rate, erc20_abi, ZERO_ADDRESS, SUPPORTED_NETWORKS, get_decimals
import os
import json
import time

MAX_256 = 2**256 - 1

CONFIG_PATH = os.path.join('chainsettle_config.json')
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
native_bridge_artifact_path = os.path.join(BASE_DIR, "..", "contracts", "out", "EscrowBridgeETH.sol", "EscrowBridgeETH.json")
token_bridge_artifact_path = os.path.join(BASE_DIR, "..", "contracts", "out", "EscrowBridge.sol", "EscrowBridge.json")

bdag_address_path = os.path.join(BASE_DIR, "..", "contracts", "deployments", "blockdag-escrow-bridge.json")
base_address_path = os.path.join(BASE_DIR, "..", "contracts", "deployments", "base-escrow-bridge.json")

with open(bdag_address_path, 'r') as f:
    NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG = json.load(f)['deployedTo']

with open(base_address_path, 'r') as f:
    TOKEN_ESCROW_BRIDGE_ADDRESS_BASE = json.load(f)['deployedTo']

with open(native_bridge_artifact_path, 'r') as f:
    native_bridge_abi = json.load(f)['abi']

with open(token_bridge_artifact_path, 'r') as f:
    token_bridge_abi = json.load(f)['abi']

escrow_bridge_config = {
    "base-sepolia": {
        "address": TOKEN_ESCROW_BRIDGE_ADDRESS_BASE,
        "abi": token_bridge_abi,
    },
    "blockdag-testnet": {
        "address": NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG,
        "abi": native_bridge_abi
    },
}

@click.group()
def cli():
    """Escrow Bridge Admin CLI"""
    pass

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of BDAG/USDC to top up the EscrowBridge contract with (normalized).")
@click.option("--network", default="base-sepolia", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
def fund_escrow(amount, network):

    settlement_ramp_network = "base" if network == "base-sepolia" else "blockdag"
    
    REGISTRY_ADDRESS = config[settlement_ramp_network]['registry_addresses']["paypal"]
    w3, account = network_func(
        network=network,
    )

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
    print(f"Using EOA = {account.address}")
    print(f"Using EscrowBridge contract = {contract_address}")

    onchain_reg_address = bridge.functions.settlementRegistry().call()
    print(f"EscrowBridge.settlementRegistry() = {onchain_reg_address}")   
    print(f"Config settlementRegistry = {REGISTRY_ADDRESS}")
    if REGISTRY_ADDRESS.lower() != onchain_reg_address.lower():
        raise Exception(
            f"❌ EscrowBridge.settlementRegistry() = {onchain_reg_address} "
            f"does not match config value {REGISTRY_ADDRESS}."
        )

    # 1) Check the “minPaymentAmount” and “maxPaymentAmount” (these are stored as raw USDC units)
    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()
    print(f"> EscrowBridge.minPaymentAmount() (raw) = {min_raw}")
    print(f"> EscrowBridge.maxPaymentAmount() (raw) = {max_raw}")

    # 2) Fetch the USDC token address that the ramp contract expects
    try:
        usdc_address = bridge.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)

        # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
        token_decimals = erc20.functions.decimals().call()
        symbol = "USDC"
        token_address = usdc_address
    except Exception as e:
        print("❌ Error fetching token details:", e)
        token_decimals = 18
        symbol = "BDAG"
        token_address = ZERO_ADDRESS
        erc20 = None
    print(f"> EscrowBridge.usdcToken() = {token_address} ({symbol})")

    # Fee
    fee = bridge.functions.fee().call()
    print(f"> EscrowBridge.fee() = {fee / 10000} ")

    # 3) Instantiate a minimal ERC20 handle so we can call decimals() and balanceOf() etc.
    # erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)

    # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
    print(f"> ERC20.decimals() = {token_decimals}")

    # 5) Convert min_raw and max_raw (which are “uint raw units”) → human USDC floats:
    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)
    print(f"  → in human {symbol}: min = {min_human:.6f}, max = {max_human:.6f} ")

    # 6) Validate the user‐supplied “amount”
    if amount < min_human or amount > max_human:
        raise ValueError(
            f"❌ Requested amount {amount} {symbol} is out of bounds: "
            f"minimum = {min_human:.6f} {symbol}, maximum = {max_human:.6f} {symbol}"
        )
    
    amount_raw = int(amount * (10 ** token_decimals))  # Convert to raw units
    top_up = amount_raw
    print(f"→ Ramp contract needs an additional {top_up} raw {symbol} units "
            f"(≈ {top_up / (10**token_decimals):.6f} {symbol}).")

    # 10.a) Check our EOA’s own USDC balance
    owner_raw_balance = erc20.functions.balanceOf(account.address).call() if erc20 else w3.eth.get_balance(account.address)
    owner_human_balance = owner_raw_balance / (10 ** token_decimals)
    print(f"> EOA {symbol} balance (raw) = {owner_raw_balance}  → (≈{owner_human_balance:.6f} {symbol})")

    if owner_raw_balance < top_up:
        raise Exception(
            f"❌ EOA’s {symbol} ({owner_human_balance:.6f} {symbol}) is less than required "
            f"{top_up / (10**token_decimals):.6f} {symbol}."
        )

    # 10.b) Build + send ERC20.approve(SettlementRamp, top_up)
    #      Fetch nonce once:
    base_nonce = w3.eth.get_transaction_count(account.address)
    if token_address != ZERO_ADDRESS:
        approved_amount = erc20.functions.allowance(account.address, contract_address).call()
        if approved_amount < top_up:
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
                raise Exception("❌ ERC20.approve(...) reverted")

            print(f"✓ Approved {top_up} raw {symbol} to EscrowBridge (tx: {h_approve.hex()})")

            time.sleep(5)  # Wait for the approval to be mined

            # 10.c) Double-check allowance
            current_allowance = erc20.functions.allowance(account.address, contract_address).call()
            print(f"🔍 Post-approve: allowance = {current_allowance} (need ≥ {top_up})")
            if current_allowance < top_up:
                raise Exception("❌ Allowance was not set correctly.")
        else:
            print(f"✓ Allowance already sufficient: {approved_amount} ≥ {top_up}")
    else:
        print("✓ No ERC20 token to approve.")

    if erc20:

        # 10.d) Now build + send EscrowBridge.fundEscrow(top_up) using nonce = base_nonce + 1
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
            raise Exception("❌ EscrowBridge.fundEscrow(...) reverted")

        print(f"✓ Funded EscrowBridge with {top_up} raw {symbol} "
                f"(≈ {top_up / (10**token_decimals):.6f} {symbol})  Tx: {h_fund.hex()}")
    else:
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
            print(f"❌ Failed to estimate gas: {e}")
            gas_est = 200000  # Fallback to a default gas estimate

        tx['gas'] = gas_est

        signed_tx = account.sign_transaction(tx)

        # Send it
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"Transaction sent: {tx_hash.hex()}")

        # Wait for confirmation (optional)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"Transaction confirmed in block {receipt.blockNumber}")
    
    time.sleep(10)
    
    # 10.e) Double-check the EscrowBridge contract’s USDC balance
    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    bridge_human_balance = bridge_raw_balance / (10 ** token_decimals)      
    print(f"🔍 Post-fund: EscrowBridge {symbol} balance (raw) = {bridge_raw_balance} "
          f"→ (≈ {bridge_human_balance:.6f} {symbol})")

@click.command()
@click.option("--network", default="base-sepolia", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
def check_exchange_rate(network):

    w3, account = network_func(
        network=network,
    )

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
    current_rate = get_exchange_rate(bridge)
    print(f"🔍 Current exchange rate: {current_rate:.6f} USD")

@click.command()
@click.option("--network", default="base-sepolia", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
@click.option("--exchange-rate", type=float, help="New exchange rate in USD.", required=True)
def update_exchange_rate(network, exchange_rate):

    w3, account = network_func(
        network=network,
    )

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)

    decimals = get_decimals(w3, bridge)

    raw_exchange_rate = int(exchange_rate * (10 ** decimals))

    current_rate = get_exchange_rate(bridge)
    print(f"🔄 Current exchange rate: {current_rate:.6f} USD")

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
        raise Exception("❌ Bridge.updateExchangeRate(...) reverted")

    print(f"✓ Updated exchange rate to {exchange_rate:.6f} USD (tx: {'0x' + h_update.hex()})")

    time.sleep(2)

    new_rate = get_exchange_rate(bridge)
    print(f"🔍 New exchange rate: {new_rate:.6f} USD")

# @click.command()
# def withdraw(network, amount):


cli.add_command(fund_escrow)
cli.add_command(check_exchange_rate)
cli.add_command(update_exchange_rate)

if __name__ == "__main__":
    cli()
