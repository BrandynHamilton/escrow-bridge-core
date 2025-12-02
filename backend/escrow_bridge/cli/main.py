import click
from escrow_bridge import (network_func, get_exchange_rate, generate_salt, get_payment,
                           ZERO_ADDRESS, SUPPORTED_NETWORKS, get_decimals, erc20_abi)
from escrow_bridge.cli import (
    console, print_status, print_panel, progress_bar, print_json, print_table, symbol_map
)
import os
import json
import time
import requests
import webbrowser
from dotenv import load_dotenv
from web3 import Web3
import secrets
from diskcache import Cache

load_dotenv()

STATUS_MAP = {
    'initialized':0,
    'registered':1,
    'attested':2,
    'confirmed':3,
    'failed':4,
    0:'initialized',
    1:'registered',
    2:'attested',
    3:'confirmed',
    4:'failed'
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Go up from escrow_bridge/cli to project root, then to contracts
CONTRACTS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "contracts")
# Using EscrowBridge (USDC version) for Base Sepolia
escrow_bridge_artifact_path = os.path.join(CONTRACTS_DIR, "out", "EscrowBridge.sol", "EscrowBridge.json")

bdag_address_path = os.path.join(CONTRACTS_DIR, "deployments", "blockdag-escrow-bridge.json")
base_address_path = os.path.join(CONTRACTS_DIR, "deployments", "base-escrow-bridge.json")

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
BLOCKDAG_TESTNET_GATEWAY_URL = os.getenv('BLOCKDAG_TESTNET_GATEWAY_URL', 'https://rpc.primordial.bdagscan.com/')
BASE_SEPOLIA_GATEWAY_URL = os.getenv('BASE_SEPOLIA_GATEWAY_URL', "https://sepolia.base.org/")
CHAINSETTLE_API_URL = os.getenv('CHAINSETTLE_API_URL', "https://api.chainsettle.tech")

with open(bdag_address_path, 'r') as f:
    ESCROW_BRIDGE_ADDRESS_BDAG = json.load(f)['deployedTo']

with open(base_address_path, 'r') as f:
    ESCROW_BRIDGE_ADDRESS_BASE = json.load(f)['deployedTo']

with open(escrow_bridge_artifact_path, 'r') as f:
    escrow_bridge_abi = json.load(f)['abi']

# Network configuration with gateway URLs and explorer URLs
NETWORK_CONFIG = {
    # "blockdag-testnet": {
    #     "address": ESCROW_BRIDGE_ADDRESS_BDAG,
    #     "abi": escrow_bridge_abi,
    #     "gateway": BLOCKDAG_TESTNET_GATEWAY_URL,
    #     "explorer": "https://primordial.bdagscan.com/tx/"
    # },
    "base-sepolia": {
        "address": ESCROW_BRIDGE_ADDRESS_BASE,
        "abi": escrow_bridge_abi,
        "gateway": BASE_SEPOLIA_GATEWAY_URL,
        "explorer": "https://sepolia.basescan.org/tx/"
    },
}

# Keep old name for compatibility
escrow_bridge_config = {net: {"address": cfg["address"], "abi": cfg["abi"]} for net, cfg in NETWORK_CONFIG.items()}

base_w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_GATEWAY_URL))
base_contract = base_w3.eth.contract(address=ESCROW_BRIDGE_ADDRESS_BASE, abi=escrow_bridge_abi)

# Fetch max escrow time with fallback
try:
    max_escrow_time = base_contract.functions.maxEscrowTime().call()
except Exception as e:
    print_status(f"Warning: Could not fetch maxEscrowTime: {e}", level="warn")
    max_escrow_time = 3600  # Default 1 hour

cache = Cache("network_lookup_cache")

TTL_SECONDS = 3600  # 1 hour

def is_chainsettle_api_running():
    try:
        r = requests.get(f"{CHAINSETTLE_API_URL}/utils/health", timeout=5)
        return r.json().get("status") == "ok"
    except Exception as e:
        print_status(f"Error connecting to ChainSettle API: {e}", level="error")
        return False

def poll_status_func(escrowId, bridge, max_attempts=60, delay=5):

    escrow_id_bytes = Web3.to_bytes(hexstr=escrowId)
    created_at = bridge.functions.payments(escrow_id_bytes).call()[8]
    max_escrow_time = bridge.functions.maxEscrowTime().call()

    for attempt in range(1, max_attempts + 1):
        elapsed_time = time.time() - created_at
        if elapsed_time > max_escrow_time:
            print_status(f"Escrow {escrowId} has exceeded max escrow time.", level="error")
            return

        time_left = max_escrow_time - elapsed_time
        minutes_left = time_left / 60
        print_status(f"Time left for escrow {escrowId}: {symbol_map['pending']}{minutes_left:.2f} minutes", level="info")

        if escrowId.startswith("0x"):
            escrowId = escrowId[2:]
        completed_escrows = bridge.functions.getCompletedEscrows().call()
        pending_escrows = bridge.functions.getPendingEscrows().call()
        isSettled = bridge.functions.isSettled(escrow_id_bytes).call()
        status_enum = bridge.functions.getSettlementStatus(escrow_id_bytes).call()
        status = STATUS_MAP.get(status_enum, "unknown")
        print_status(f"Oracle status: {status.upper()}", level="info")

        if escrow_id_bytes in completed_escrows:
            print_status(f"Escrow {escrowId} is completed.", level="success")
            break
        elif escrow_id_bytes in pending_escrows:
            print_status(f"Escrow {escrowId} is still pending...", level="warn")
            time.sleep(delay)
            continue
        else:
            if isSettled:
                print_status(f"Escrow {escrowId} is settled but not in completed escrows.", level="success")
                break
            else:
                print_status(f"Escrow {escrowId} not found in pending or completed escrows.", level="error")
                break

def find_network_for_settlement(settlement_id):
    """
    Look for the network and registry type that contains the given settlement_id.
    First checks cache, then falls back to RPC calls if not cached.
    Returns (network, contract) on success, else (None, None).
    """

    if isinstance(settlement_id, str):
        settlement_id = Web3.to_bytes(hexstr=settlement_id)

    cached_result = cache.get(settlement_id.hex())
    if cached_result:
        network = cached_result["network"]
        address = cached_result["address"]
        abi = escrow_bridge_config[network]["abi"]
        contract = base_w3.eth.contract(address=address, abi=abi)
        return network, contract

    for net in SUPPORTED_NETWORKS:
        w3 = base_w3
        address = escrow_bridge_config[net]["address"]
        abi = escrow_bridge_config[net]["abi"]

        try:
            contract = w3.eth.contract(address=address, abi=abi)
        except Exception as e:
            print_status(f"Error loading contract for {net}: {e}", level="error")
            continue

        for attempt in range(3):
            try:
                payment = contract.functions.payments(settlement_id).call()

                # if escrow was never initialized, payer will be address(0)
                if payment[0] != "0x0000000000000000000000000000000000000000":
                    entry = {
                        "network": net,
                        "address": address,
                    }
                    contract = w3.eth.contract(address=address, abi=abi)
                    # Store in cache with TTL
                    cache.set(settlement_id.hex(), entry, expire=TTL_SECONDS)
                    return net, contract

                break  # stop retry loop if not found
            except Exception as call_error:
                print_status(f"{net}: {call_error}", level="warn")
                time.sleep(1)

    return None, None

@click.group()
def cli():
    """Escrow Bridge Contract CLI"""
    pass

@click.command()
def health():
    """Check if ChainSettle Oracle is reachable."""
    print_panel("Checking ChainSettle Oracle health...")
    with progress_bar("Connecting...") as progress:
        task = progress.add_task("Checking health...", total=None)
        result = is_chainsettle_api_running()

    if result:
        print_status("ChainSettle Oracle is reachable.", level="success")
    else:
        print_status("ChainSettle Oracle is not reachable.", level="error")

@click.command()
def config():
    """Display Escrow Bridge configuration."""
    print_panel("Escrow Bridge Configuration", tone="info")

    config_display = {}
    for net in SUPPORTED_NETWORKS:
        config_display[net] = {"address": escrow_bridge_config[net]["address"]}

    print_json(config_display)

@click.command()
@click.option("--escrow-id", default=None, help="The escrow ID hash to fetch details for.")
def payment_info(escrow_id):
    """Fetch payment info for an escrow ID."""
    # Use global if not passed as argument
    if escrow_id is None:
        escrow_id = cache.get("last_escrow_id")
        if not escrow_id:
            print_status("No escrow ID provided and no cached escrow_id found.", level="error")
            raise click.ClickException("No escrow ID provided.")

    print_panel(f"Fetching payment info\nEscrow ID: {escrow_id[:20]}...", tone="info")

    with progress_bar("Fetching...") as progress:
        task = progress.add_task("Loading payment data...", total=None)
        escrow_id_bytes = Web3.to_bytes(hexstr=escrow_id)
        network, bridge = find_network_for_settlement(escrow_id)

    if not network:
        print_status(f"Could not find network for escrow ID {escrow_id}", level="error")
        raise click.ClickException(f"Network not found for escrow ID.")

    data = get_payment(escrow_id_bytes, bridge)

    # USDC has 6 decimals
    data['requestedAmount'] = data.get("requestedAmount") / 1e6
    data['requestedAmountUsd'] = data.get("requestedAmountUsd") / 1e6

    data['postedAmount'] = data.get("postedAmount") / 1e6
    data['postedAmountUsd'] = data.get("postedAmountUsd") / 1e6
    data['network'] = network

    print_status("Payment details retrieved successfully.", level="success")
    print_json({"escrow_id": escrow_id, "data": data})

@click.command()
@click.option("--escrow-id", default=None, help="The escrow ID to poll status for.")
@click.option("--timeout", default=300, type=int, help="Maximum time to poll in seconds.")
@click.option("--delay", default=10, type=int, help="Delay between polling attempts in seconds.")
def poll_status(escrow_id, timeout, delay):
    """Poll the status of an escrow until completion."""
    # Use global if not passed as argument
    if escrow_id is None:
        escrow_id = cache.get("last_escrow_id")
        if not escrow_id:
            print_status("No escrow ID provided and no cached escrow_id found.", level="error")
            raise click.ClickException("No escrow ID provided.")

    network, bridge = find_network_for_settlement(escrow_id)
    if not network:
        print_status(f"Could not find network for escrow ID {escrow_id}", level="error")
        raise click.ClickException(f"Network not found.")

    print_panel(f"Polling escrow status\nID: {escrow_id[:20]}...\nNetwork: {network}", tone="info")

    max_attempts = timeout // delay
    poll_status_func(escrow_id, bridge, max_attempts, delay)

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of BDAG/USDC you wish to receive.")
@click.option("--network", default="base-sepolia", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
@click.option("--recipient", default=None, type=str, help="EVM address of the recipient, defaults to sender address if not provided.")
@click.option(
    "--private-key",
    envvar="PRIVATE_KEY",
    prompt="Enter your private key",
    hide_input=True,
    help="Private key for the sender account"
)
@click.option("-f", "--force", is_flag=True, help="Force the payment even if ChainSettle API is unreachable or account is under estimated gas.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output.")
@click.option("--gas-estimate-factor", default=1.25, type=float, help="Factor to scale the gas estimate by.")
def pay(amount, network, recipient, private_key, force, verbose, gas_estimate_factor):
    """Initialize escrow, register with oracle, and poll for settlement."""
    print_panel("Initialize Escrow", tone="info")
    print_status(f"Initializing escrow on {network} for amount: {amount}...", level="info")

    GATEWAY = NETWORK_CONFIG[network]["gateway"]
    EXPL_URL = NETWORK_CONFIG[network]["explorer"]

    try:
        w3 = Web3(Web3.HTTPProvider(GATEWAY))
        account = w3.eth.account.from_key(private_key)
    except Exception as e:
        print_status(f"Error setting up Web3 or account: {e}", level="error")
        raise click.ClickException(str(e))

    if not is_chainsettle_api_running():
        if not force:
            print_status("ChainSettle API is not reachable. Off-chain registration may fail.", level="error")
            raise click.ClickException("ChainSettle API unreachable. Use --force to proceed anyway.")
        else:
            print_status("ChainSettle API is not reachable, but proceeding due to --force flag.", level="warn")

    if not recipient:
        recipient = account.address

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
    max_escrow_time = bridge.functions.maxEscrowTime().call()

    recipient_email = bridge.functions.recipientEmail().call()

    # Display contract info
    rows = [
        ("Recipient Email", recipient_email),
        ("Contract", contract_address[:20] + "..."),
        ("Network", network),
    ]
    print_table(["Field", "Value"], rows, title="Contract Info")

    # Check limits
    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()

    try:
        usdc_address = bridge.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)
        token_decimals = erc20.functions.decimals().call()
        symbol = "USDC"
        token_address = usdc_address
    except Exception as e:
        token_decimals = 18
        symbol = "BDAG"
        token_address = ZERO_ADDRESS
        erc20 = None

    fee = bridge.functions.fee().call()
    FEE_DENOMINATOR = bridge.functions.FEE_DENOMINATOR().call()
    fee_percent = fee / FEE_DENOMINATOR

    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)

    if amount < min_human or amount > max_human:
        print_status(f"Amount {amount} {symbol} out of bounds: min={min_human:.6f}, max={max_human:.6f}", level="error")
        raise click.ClickException("Amount out of bounds.")

    amount_raw = int(amount * (10 ** token_decimals))

    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    ramp_usdc_balance = bridge.functions.getFreeBalance().call()
    human_ramp_balance = ramp_usdc_balance / (10 ** token_decimals)

    if amount > human_ramp_balance:
        print_status(f"Amount {amount} {symbol} exceeds available funds ({human_ramp_balance:.6f} {symbol})", level="error")
        raise click.ClickException("Insufficient bridge funds.")

    salt = generate_salt()
    if not salt.startswith("0x"):
        salt = "0x" + salt

    salt_bytes = Web3.to_bytes(hexstr=salt)
    settlement_id = secrets.token_hex(18)

    escrow_id_bytes = w3.solidity_keccak(
        ["bytes32", "string"],
        [salt_bytes, settlement_id]
    )

    escrow_id = escrow_id_bytes.hex()
    print_status(f"Computed escrow_id = {escrow_id[:24]}...", level="highlight")

    # Build and send transaction
    print_status("Building transaction...", level="info")

    with progress_bar("Sending transaction...") as progress:
        task = progress.add_task("Submitting to blockchain...", total=None)

        base_tx = bridge.functions.initPayment(
            escrow_id_bytes,
            amount_raw,
            recipient
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, 'pending'),
        })
        gas_est = w3.eth.estimate_gas(base_tx)
        gas_est_scaled = int(gas_est * gas_estimate_factor)

        balance = w3.eth.get_balance(account.address)

        latest_block = w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
        priority_fee = w3.to_wei(2, "gwei")
        max_fee = base_fee + priority_fee

        est_cost = gas_est_scaled * max_fee

        if balance < est_cost:
            if not force:
                print_status(f"Insufficient ETH for gas. Balance={w3.from_wei(balance, 'ether')} ETH, Required={w3.from_wei(est_cost, 'ether')} ETH", level="error")
                raise click.ClickException("Insufficient ETH for gas.")
            else:
                print_status("Insufficient ETH for gas, but proceeding due to --force flag.", level="warn")

        base_tx.update({
            "gas": gas_est_scaled,
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2
        })
        signed_init = account.sign_transaction(base_tx)
        h_init = w3.eth.send_raw_transaction(signed_init.raw_transaction)
        receipt_init = w3.eth.wait_for_transaction_receipt(h_init)

    if receipt_init.status != 1:
        print_status("EscrowBridge.initPayment(...) reverted", level="error")
        raise click.ClickException("Transaction reverted.")

    print_status(f"initPayment submitted {symbol_map['arrow']} Tx: 0x{h_init.hex()[:16]}...", level="success")
    print_status(f"Explorer: {EXPL_URL}0x{h_init.hex()}", level="info")

    # Register with oracle
    print_panel("Register Escrow", tone="info")
    print_status("Registering offchain data with the ChainSettle oracle...", level="info")

    with progress_bar("Registering...") as progress:
        task = progress.add_task("Contacting oracle...", total=None)
        payload = {
            "salt": salt,
            "settlement_id": settlement_id,
            "recipient_email": recipient_email,
        }
        headers = {"content-type": "application/json"}
        r = requests.post(f"{CHAINSETTLE_API_URL}/settlement/register_settlement",
                         json=payload, headers=headers)
        r.raise_for_status()
        resp = r.json()

    if 'user_url' in resp.get('settlement_info', {}):
        print_status(f"User URL: {resp['settlement_info']['user_url']}", level="success")
        webbrowser.open(resp['settlement_info']['user_url'])
    else:
        print_status("User URL not found in response.", level="warn")

    old_balance = erc20.functions.balanceOf(recipient).call() if erc20 else w3.eth.get_balance(recipient)
    old_human_balance = old_balance / (10 ** token_decimals)

    # Poll status
    print_panel("Polling Escrow Status", tone="info")
    poll_status_func(escrow_id, bridge)

    new_balance = erc20.functions.balanceOf(recipient).call() if erc20 else w3.eth.get_balance(recipient)
    new_human_balance = new_balance / (10 ** token_decimals)

    # Display balance changes
    rows = [
        ("Before", f"{old_human_balance:.6f} {symbol}"),
        ("After", f"{new_human_balance:.6f} {symbol}"),
        ("Change", f"+{new_human_balance - old_human_balance:.6f} {symbol}"),
    ]
    print_table(["Balance", "Amount"], rows, title="User Balance")

    escrow = get_payment(escrow_id_bytes, bridge)

    print_panel("Final Escrow Payment Details", tone="success")

    # USDC has 6 decimals
    escrow['requestedAmount'] = escrow.get("requestedAmount") / 1e6
    escrow['requestedAmountUsd'] = escrow.get("requestedAmountUsd") / 1e6

    escrow['postedAmount'] = escrow.get("postedAmount") / 1e6
    escrow['postedAmountUsd'] = escrow.get("postedAmountUsd") / 1e6
    escrow["escrow_id"] = escrow_id
    escrow["network"] = network

    cache.set("last_salt", salt)
    cache.set("last_settlement_id", settlement_id)
    cache.set("last_escrow_id", escrow_id)

    print_json(escrow)
    print_status("Payment complete.", level="success")

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of BDAG/USDC you wish to receive.")
@click.option("--network", default="base-sepolia", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
@click.option("--recipient", default=None, type=str, help="EVM address of the recipient, defaults to sender address if not provided.")
@click.option(
    "--private-key",
    envvar="PRIVATE_KEY",
    prompt="Enter your private key",
    hide_input=True,
    help="Private key for the sender account"
)
@click.option("--gas-estimate-factor", default=1.25, type=float, help="Factor to scale the gas estimate by.")
@click.option("-f", "--force", is_flag=True, help="Force the payment even if account is under estimated gas.")
def init_escrow(amount, network, recipient, private_key, gas_estimate_factor, force):
    """Initialize an escrow payment on-chain only (no oracle registration)."""
    print_panel("Initialize Escrow (On-chain Only)", tone="info")

    GATEWAY = NETWORK_CONFIG[network]["gateway"]
    EXPL_URL = NETWORK_CONFIG[network]["explorer"]

    print_status(f"Initializing escrow on {network} for amount: {amount}...", level="info")

    try:
        w3 = Web3(Web3.HTTPProvider(GATEWAY))
        account = w3.eth.account.from_key(private_key)
        print_status(f"Using account: {account.address[:20]}...", level="info")
    except Exception as e:
        print_status(f"Error setting up Web3 or account: {e}", level="error")
        raise click.ClickException(str(e))

    if not is_chainsettle_api_running():
        print_status("ChainSettle API is not reachable, but can proceed onchain.", level="warn")

    if not recipient:
        recipient = account.address

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)

    recipient_email = bridge.functions.recipientEmail().call()
    print_status(f"Recipient Email: {recipient_email}", level="info")

    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()

    try:
        usdc_address = bridge.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)
        token_decimals = erc20.functions.decimals().call()
        symbol = "USDC"
        token_address = usdc_address
    except Exception as e:
        token_decimals = 18
        symbol = "BDAG"
        token_address = ZERO_ADDRESS
        erc20 = None

    fee = bridge.functions.fee().call()
    FEE_DENOMINATOR = bridge.functions.FEE_DENOMINATOR().call()
    fee_percent = fee / FEE_DENOMINATOR
    print_status(f"Fee: {fee_percent * 100:.2f}%", level="info")

    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)

    if amount < min_human or amount > max_human:
        print_status(f"Amount {amount} {symbol} out of bounds: min={min_human:.6f}, max={max_human:.6f}", level="error")
        raise click.ClickException("Amount out of bounds.")

    amount_raw = int(amount * (10 ** token_decimals))

    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    ramp_usdc_balance = bridge.functions.getFreeBalance().call()
    human_ramp_balance = ramp_usdc_balance / (10 ** token_decimals)

    if amount > human_ramp_balance:
        print_status(f"Amount {amount} {symbol} exceeds available funds ({human_ramp_balance:.6f} {symbol})", level="error")
        raise click.ClickException("Insufficient bridge funds.")

    salt = generate_salt()
    if not salt.startswith("0x"):
        salt = "0x" + salt

    salt_bytes = Web3.to_bytes(hexstr=salt)
    settlement_id = secrets.token_hex(18)

    escrow_id_bytes = w3.solidity_keccak(
        ["bytes32", "string"],
        [salt_bytes, settlement_id]
    )

    escrow_id = escrow_id_bytes.hex()
    print_status(f"Computed escrow_id = {escrow_id[:24]}...", level="highlight")

    with progress_bar("Sending transaction...") as progress:
        task = progress.add_task("Submitting to blockchain...", total=None)

        base_tx = bridge.functions.initPayment(
            escrow_id_bytes,
            amount_raw,
            recipient
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, 'pending'),
        })
        gas_est = w3.eth.estimate_gas(base_tx)
        gas_est_scaled = int(gas_est * gas_estimate_factor)

        balance = w3.eth.get_balance(account.address)
        print_status(f"Account balance: {w3.from_wei(balance, 'ether')} ETH", level="info")

        latest_block = w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
        priority_fee = w3.to_wei(2, "gwei")
        max_fee = base_fee + priority_fee

        est_cost = gas_est_scaled * max_fee
        print_status(f"Estimated gas: {w3.from_wei(est_cost, 'ether')} ETH", level="info")

        if balance < est_cost:
            if not force:
                print_status(f"Insufficient ETH for gas.", level="error")
                raise click.ClickException("Insufficient ETH.")
            else:
                print_status("Insufficient ETH, proceeding due to --force flag.", level="warn")

        base_tx.update({
            "gas": gas_est_scaled,
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2
        })
        signed_init = account.sign_transaction(base_tx)
        h_init = w3.eth.send_raw_transaction(signed_init.raw_transaction)
        receipt_init = w3.eth.wait_for_transaction_receipt(h_init)

    if receipt_init.status != 1:
        print_status("EscrowBridge.initPayment(...) reverted", level="error")
        raise click.ClickException("Transaction reverted.")

    print_status(f"initPayment submitted {symbol_map['arrow']} Tx: 0x{h_init.hex()}", level="success")
    print_status(f"Explorer: {EXPL_URL}0x{h_init.hex()}", level="info")

    info = {
        "settlement_id": settlement_id,
        "salt": salt,
        "escrow-id": escrow_id,
        "tx-hash": "0x" + h_init.hex(),
        "amount": amount,
        "symbol": symbol,
        "recipient": recipient,
        "network": network
    }

    cache.set("last_salt", salt)
    cache.set("last_settlement_id", settlement_id)
    cache.set("last_escrow_id", escrow_id)

    print_status("Escrow initialized successfully.", level="success")
    print_json(info)

@click.command()
@click.option("--salt", default = None, help="The salt used in the escrow initialization.")
@click.option("--settlement-id", default = None,  help="The settlement ID used in the escrow initialization.")
def register_settlement(salt, settlement_id):
    """Register escrow offchain data with the ChainSettle oracle."""
    print_panel("Register Escrow", tone="info")
    print_status("Registering offchain data with the ChainSettle oracle...", level="info")

    if not is_chainsettle_api_running():
        print_status("ChainSettle API is not reachable. Off-chain registration will fail.", level="error")
        raise click.ClickException("ChainSettle API unreachable.")

    # Use global if not passed as argument
    if salt is None:
        salt = cache.get("last_salt")
        if not salt:
            print_status("No salt provided and no cached salt found.", level="error")
            raise click.ClickException("No salt provided.")

    if settlement_id is None:
        settlement_id = cache.get("last_settlement_id")
        if not settlement_id:
            print_status("No settlement ID provided and no cached settlement_id found.", level="error")
            raise click.ClickException("No settlement ID provided.")

    with progress_bar("Registering...") as progress:
        task = progress.add_task("Contacting oracle...", total=None)
        payload = {
            "salt": salt,
            "settlement_id": settlement_id,
            "recipient_email": "treasury@lp.com",
        }
        headers = {"content-type": "application/json"}
        r = requests.post(f"{CHAINSETTLE_API_URL}/settlement/register_settlement",
                         json=payload, headers=headers)
        r.raise_for_status()
        resp = r.json()

    if 'user_url' in resp.get('settlement_info', {}):
        print_status(f"User URL: {resp['settlement_info']['user_url']}", level="success")
        webbrowser.open(resp['settlement_info']['user_url'])
    else:
        print_status("User URL not found in response.", level="warn")

@click.command()
@click.option("--escrow-id", default = None, help="The escrow ID hash to settle.")
@click.option(
    "--private-key",
    envvar="PRIVATE_KEY",
    prompt="Enter your private key",
    hide_input=True,
    help="Private key for the sender account"
)
@click.option("--gas-estimate-factor", default=1.25, type=float, help="Factor to scale the gas estimate by.")
def settle(escrow_id, private_key, gas_estimate_factor):
    """Manually settle an escrow payment on-chain."""
    print_panel("Settle Escrow", tone="info")
    print_status("Settling escrow onchain...", level="info")

    # Use global if not passed as argument
    if escrow_id is None:
        escrow_id = cache.get("last_escrow_id")
        if not escrow_id:
            print_status("No escrow ID provided and no cached escrow_id found.", level="error")
            raise click.ClickException("No escrow ID provided.")

    escrow_id_bytes = Web3.to_bytes(hexstr=escrow_id)

    network, bridge = find_network_for_settlement(escrow_id)
    if not network:
        print_status(f"Could not find network for escrow ID {escrow_id}", level="error")
        raise click.ClickException("Network not found.")

    is_settled = bridge.functions.isSettled(escrow_id_bytes).call()
    if is_settled:
        print_status(f"Escrow ID {escrow_id[:20]}... is already settled on {network}.", level="warn")
        return

    GATEWAY = NETWORK_CONFIG[network]["gateway"]
    EXPL_URL = NETWORK_CONFIG[network]["explorer"]

    print_status(f"Settling escrow ID: {escrow_id[:20]}... on {network}", level="info")

    try:
        w3 = Web3(Web3.HTTPProvider(GATEWAY))
        account = w3.eth.account.from_key(private_key)
    except Exception as e:
        print_status(f"Error setting up Web3 or account: {e}", level="error")
        raise click.ClickException(str(e))

    with progress_bar("Settling...") as progress:
        task = progress.add_task("Submitting settlement transaction...", total=None)

        base_tx = bridge.functions.settlePayment(escrow_id_bytes).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        })

        try:
            gas_est = w3.eth.estimate_gas(base_tx)
        except Exception as e:
            gas_est = 200000
            print_status(f"Error estimating gas: {e}", level="warn")

        latest_block = w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
        priority_fee = w3.to_wei(2, "gwei")
        max_fee = base_fee + priority_fee

        base_tx.update({
            "gas": int(gas_est * gas_estimate_factor),
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2
        })

        signed_tx = account.sign_transaction(base_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status == 1:
        print_status(f"Payment settled {symbol_map['arrow']} {EXPL_URL}0x{tx_hash.hex()}", level="success")
    else:
        print_status(f"Transaction failed {symbol_map['arrow']} {EXPL_URL}0x{tx_hash.hex()}", level="error")

cli.add_command(pay)
cli.add_command(init_escrow)
cli.add_command(register_settlement)
cli.add_command(settle)
cli.add_command(poll_status)
cli.add_command(payment_info)
cli.add_command(health)
cli.add_command(config)

if __name__ == "__main__":
    cli()
