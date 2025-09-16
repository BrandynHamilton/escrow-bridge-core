import click
from escrow_bridge import (network_func, get_exchange_rate, generate_salt, get_payment,
                           ZERO_ADDRESS, SUPPORTED_NETWORKS, get_decimals, erc20_abi)
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
native_bridge_artifact_path = os.path.join(BASE_DIR, "..", "contracts", "out", "EscrowBridgeETH.sol", "EscrowBridgeETH.json")
token_bridge_artifact_path = os.path.join(BASE_DIR, "..", "contracts", "out", "EscrowBridge.sol", "EscrowBridge.json")

bdag_address_path = os.path.join(BASE_DIR, "..", "contracts", "deployments", "blockdag-escrow-bridge.json")
base_address_path = os.path.join(BASE_DIR, "..", "contracts", "deployments", "base-escrow-bridge.json")

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
BASE_SEPOLIA_GATEWAY_URL = os.getenv('BASE_SEPOLIA_GATEWAY_URL', 'https://sepolia.base.org/')
BLOCKDAG_TESTNET_GATEWAY_URL = os.getenv('BLOCKDAG_TESTNET_GATEWAY_URL', 'https://rpc.primordial.bdagscan.com/')
CHAINSETTLE_API_URL = os.getenv('CHAINSETTLE_API_URL', "https://api.chainsettle.tech")

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

base_w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_GATEWAY_URL))

bdag_w3 = Web3(Web3.HTTPProvider(BLOCKDAG_TESTNET_GATEWAY_URL))

base_contract = base_w3.eth.contract(address=TOKEN_ESCROW_BRIDGE_ADDRESS_BASE, abi=token_bridge_abi)
blockdag_contract = bdag_w3.eth.contract(address=NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG, abi=native_bridge_abi)

usdc_address = base_contract.functions.usdcToken().call()
erc20 = base_w3.eth.contract(address=usdc_address, abi=erc20_abi)
max_escrow_time = blockdag_contract.functions.maxEscrowTime().call()

cache = Cache("network_lookup_cache")

TTL_SECONDS = 3600  # 1 hour

# for net, cfg in escrow_bridge_config.items():
#     print(f"  {net}: {cfg['address']}")

def is_chainsettle_api_running():
    try:
        r = requests.get(f"{CHAINSETTLE_API_URL}/utils/health", timeout=5)
        return r.json().get("status") == "ok"
    except Exception as e:
        click.echo(f"Error connecting to ChainSettle API: {e}")
        return False

def poll_status_func(escrowId, bridge, max_attempts=60, delay=5):
    
    escrow_id_bytes = Web3.to_bytes(hexstr=escrowId)
    created_at = bridge.functions.payments(escrow_id_bytes).call()[8]
    max_escrow_time = bridge.functions.maxEscrowTime().call()

    for attempt in range(1, max_attempts + 1):
        elapsed_time = time.time() - created_at
        if elapsed_time > max_escrow_time:
            click.secho(f"⚠️ Escrow {escrowId} has exceeded max escrow time.", fg="red")
            return

        time_left = max_escrow_time - elapsed_time
        minutes_left = time_left / 60
        click.secho(f"⏳ Time left for escrow {escrowId}: ≈{minutes_left:.2f} minutes", fg="black")

        if escrowId.startswith("0x"):
            escrowId = escrowId[2:]
        # print(f"[Attempt {attempt}] Checking status for {escrowId}...")
        completed_escrows = bridge.functions.getCompletedEscrows().call()
        pending_escrows = bridge.functions.getPendingEscrows().call()
        isSettled = bridge.functions.isSettled(escrow_id_bytes).call()
        status_enum = bridge.functions.getSettlementStatus(escrow_id_bytes).call()
        status = STATUS_MAP.get(status_enum, "unknown")
        click.echo(f"Oracle status: {status.upper()}")

        if escrow_id_bytes in completed_escrows:
            click.secho(f"✅ Escrow {escrowId} is completed.", fg="green")
            break
        elif escrow_id_bytes in pending_escrows:
            click.secho(f"⏳ Escrow {escrowId} is still pending...", fg="yellow")
            time.sleep(delay)
            continue
        else:
            if isSettled:
                click.secho(f"✅ Escrow {escrowId} is settled but not in completed escrows.", fg="green")
                break
            else:
                click.secho(f"❌ Escrow {escrowId} not found in pending or completed escrows.", fg="red")
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
        w3 = bdag_w3 if network == "blockdag-testnet" else base_w3
        contract = w3.eth.contract(address=address, abi=abi)
        return network, contract

    for net in SUPPORTED_NETWORKS:
        try:
            if net == "blockdag-testnet":
                w3 = bdag_w3
            else:
                w3 = base_w3
        except Exception as e:
            click.echo(f"[find_network] Error connecting to {net}: {e}")
            continue

        address = escrow_bridge_config[net]["address"]
        abi = escrow_bridge_config[net]["abi"]

        try:
            contract = w3.eth.contract(address=address, abi=abi)
        except Exception as e:
            click.echo(f"[find_network] Error loading contract for {net}: {e}")
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
                click.echo(f"[find_network] {net}: {call_error}")
                time.sleep(1)

    return None, None

@click.group()
def cli():
    """Escrow Bridge Contract CLI"""
    pass

@click.command()
def health():
    if is_chainsettle_api_running():
        click.secho("✅ ChainSettle Oracle is reachable.", fg="green")
    else:
        click.secho("❌ ChainSettle Oracle is not reachable.", fg="red")

@click.command()
def config():
    click.secho("Escrow Bridge Configuration:", fg="blue")
    for net in SUPPORTED_NETWORKS:
        if "abi" in escrow_bridge_config[net]:
            escrow_bridge_config[net].pop("abi")  # Remove ABI for cleaner output
    click.echo(json.dumps(escrow_bridge_config, indent=4))

@click.command()
@click.option("--escrow-id", default=None, help="The escrow ID hash to fetch details for.")
def payment_info(escrow_id):

    # Use global if not passed as argument
    if escrow_id is None:
        escrow_id = cache.get("last_escrow_id")
        if not escrow_id:  
            raise ValueError("❌ No escrow ID provided and no cached escrow_id found.")

    click.secho(f"Fetching payment info for Escrow ID: {escrow_id}")
    escrow_id_bytes = Web3.to_bytes(hexstr=escrow_id)

    network, bridge = find_network_for_settlement(escrow_id)
    if not network:
        raise ValueError(f"❌ Could not find network for escrow ID {escrow_id}")

    data = get_payment(escrow_id_bytes, bridge)

    data['requestedAmount'] = data.get("requestedAmount") / 1e6 if network == "base-sepolia" else data.get("requestedAmount") / 1e18
    data['requestedAmountUsd'] = data.get("requestedAmountUsd") / 1e6

    data['postedAmount'] = data.get("postedAmount") / 1e6 if network == "base-sepolia" else data.get("postedAmount") / 1e18
    data['postedAmountUsd'] = data.get("postedAmountUsd") / 1e6
    data['network'] = network

    struct = {
        "escrow_id": escrow_id,
        "data": data
    }

    click.secho("Payment details:", fg="blue")
    click.echo(json.dumps(struct, indent=4))

@click.command()
@click.option("--escrow-id", default=None, help="The escrow ID to poll status for.")
@click.option("--timeout", default=300, type=int, help="Maximum time to poll in seconds.")
@click.option("--delay", default=10, type=int, help="Delay between polling attempts in seconds.")
def poll_status(escrow_id, timeout, delay):

    # Use global if not passed as argument
    if escrow_id is None:
        escrow_id = cache.get("last_escrow_id")
        if not escrow_id:  
            raise ValueError("❌ No escrow ID provided and no cached escrow_id found.")

    network, bridge = find_network_for_settlement(escrow_id)
    if not network:
        raise ValueError(f"❌ Could not find network for escrow ID {escrow_id}")

    click.secho(f"Polling status for escrow ID: {escrow_id} on network: {network}")

    GATEWAY = BLOCKDAG_TESTNET_GATEWAY_URL if network == "blockdag-testnet" else BASE_SEPOLIA_GATEWAY_URL

    max_attempts = timeout // delay

    poll_status_func(escrow_id, bridge, max_attempts, delay)

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of BDAG/USDC you wish to receive.")
@click.option("--network", default="blockdag-testnet", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
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
    click.secho("\n=== Initialize Escrow ===", bold=True)
    click.echo(f"Initializing escrow on {network} for amount: {amount}...")
    GATEWAY = BLOCKDAG_TESTNET_GATEWAY_URL if network == "blockdag-testnet" else BASE_SEPOLIA_GATEWAY_URL
    EXPL_URL = "https://sepolia-explorer.base.org/tx/" if network == "base-sepolia" else "https://primordial.bdagscan.com/tx/"

    try:
        w3 = Web3(Web3.HTTPProvider(GATEWAY))
        account = w3.eth.account.from_key(private_key)
    except Exception as e:
        raise ValueError(f"❌ Error setting up Web3 or account: {e}")
    
    if not is_chainsettle_api_running():
        if not force:
            raise ValueError("⚠️    Warning: ChainSettle API is not reachable. Off-chain registration may fail.")
        else:
            click.secho("⚠️    Warning: ChainSettle API is not reachable, but proceeding due to --force flag.", fg="red")

    if not recipient:
        recipient = account.address

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
    max_escrow_time = bridge.functions.maxEscrowTime().call()

    recipient_email = bridge.functions.recipientEmail().call()
    click.echo(f"> EscrowBridge PayPal Recipient = {recipient_email}")

    # 1) Check the “minPaymentAmount” and “maxPaymentAmount” (these are stored as raw USDC units)
    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()

    # 2) Fetch the USDC token address that the ramp contract expects
    try:
        usdc_address = bridge.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)

        # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
        token_decimals = erc20.functions.decimals().call()
        symbol = "USDC"
        token_address = usdc_address
    except Exception as e:
        # print("❌ Error fetching token details:", e)
        token_decimals = 18
        symbol = "BDAG"
        token_address = ZERO_ADDRESS
        erc20 = None
    click.echo(f"> EscrowBridge Asset = {token_address} ({symbol})")

    fee = bridge.functions.fee().call()
    # print(f"> EscrowBridge.fee() = {fee} {symbol}")

    FEE_DENOMINATOR = bridge.functions.FEE_DENOMINATOR().call()
    # print(f"> EscrowBridge.FEE_DENOMINATOR() = {FEE_DENOMINATOR}")

    fee_percent = fee / FEE_DENOMINATOR
    click.echo(f"> EscrowBridge → fee percentage = {fee_percent * 100:.2f}%")

    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)
    # print(f"> EscrowBridge.minPaymentAmount() (human) = {min_human:.6f}")
    # print(f"> EscrowBridge.maxPaymentAmount() (human) = {max_human:.6f}")

    # 6) Validate the user‐supplied “amount”
    if amount < min_human or amount > max_human:
        raise ValueError(
            f"❌ Requested amount {amount} {symbol} is out of bounds: "
            f"minimum = {min_human:.6f} {symbol}, maximum = {max_human:.6f} {symbol}"
        )

    amount_raw = int(amount * (10 ** token_decimals))  # Convert to raw units

    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    bridge_human_balance = bridge_raw_balance / (10 ** token_decimals)  

    ramp_usdc_balance = bridge.functions.getFreeBalance().call()
    human_ramp_balance = ramp_usdc_balance / (10 ** token_decimals)
    # print(f"> EscrowBridge {symbol} balance (raw) = {ramp_usdc_balance}")
    # print(f"  → in human {symbol} = {human_ramp_balance:.6f} {symbol}")

    # print(f"> EscrowBridge {symbol} balance (raw) = {bridge_raw_balance}  → (≈{bridge_human_balance:.6f} {symbol})")
    # print(f" EscrowBridge free balance: (≈{human_ramp_balance:.6f} {symbol})")

    if amount > human_ramp_balance:
        raise ValueError(
            f"❌ Requested amount {amount} {symbol} exceeds available funds "
            f"(≈{human_ramp_balance:.6f} {symbol})"
        )
    
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
    click.secho(f"> Computed escrow_id = {escrow_id}", fg="blue")

    base_tx = bridge.functions.initPayment(
        escrow_id_bytes,
        amount_raw,
        recipient
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, 'pending'),
    })
    gas_est = w3.eth.estimate_gas(base_tx)
    gas_est_scaled = int(gas_est * gas_estimate_factor)  # Add buffer

    balance = w3.eth.get_balance(account.address)

    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
    priority_fee = w3.to_wei(2, "gwei")
    max_fee = base_fee + priority_fee

    est_cost = gas_est_scaled * max_fee

    if balance < est_cost:
        if not force:
            raise ValueError(
                f"❌ Insufficient ETH for estimated gas. "
                f"Balance = {w3.from_wei(balance, 'ether')} ETH, "
                f"Required ≈ {w3.from_wei(est_cost, 'ether')} ETH"
            )
        else:
            click.secho("⚠️ Warning: Insufficient ETH for estimated gas, but proceeding due to --force flag.", fg="red")

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
        raise Exception("❌ EscrowBridge.initPayment(...) reverted")

    click.secho(f"✓ initPayment({escrow_id}, {amount:.6f} {symbol}) submitted → Tx: {'0x' + h_init.hex()}", fg="green")
    click.secho(f"→ View on Explorer: {EXPL_URL}{'0x' + h_init.hex()}", fg="blue")

    # totalEscrowed = bridge.functions.totalEscrowed().call()
    # print(f"EscrowBridge.totalEscrowed() = {totalEscrowed} raw {symbol}")

    # ─────────────────────────────────────────────────────────────────────────
    # 12) Store salt off‐chain, then poll for settlement to finalize.
    # The frontend would need to do this, but we do it here for demonstration.
    # Note: The ChainSettleService is a wrapper around the ChainSettle API.
    # ─────────────────────────────────────────────────────────────────────────
    click.secho("\n=== Register Escrow ===", bold=True)
    click.echo("Registering offchain data with the ChainSettle oracle...")
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
        click.secho(f"✅ User URL: {resp['settlement_info']['user_url']}", fg="green")
        webbrowser.open(resp['settlement_info']['user_url'])
    else:
        raise ValueError("⚠️ User URL not found in response.")

    # We can also poll settlement activity directly in the smart contract.

    old_balance = erc20.functions.balanceOf(recipient).call() if erc20 else w3.eth.get_balance(recipient)
    old_human_balance = old_balance / (10 ** token_decimals)

    click.secho("\n=== Polling Escrow Status ===", bold=True)

    poll_status_func(escrow_id, bridge)

    new_balance = erc20.functions.balanceOf(recipient).call() if erc20 else w3.eth.get_balance(recipient)
    new_human_balance = new_balance / (10 ** token_decimals)

    click.secho(f"User's {symbol} balance before settlement: {old_balance} raw units "
          f"(≈ {old_human_balance:.6f} {symbol})", fg="blue")

    click.secho(f"User's {symbol} balance after settlement: {new_balance} raw units "
          f"(≈ {new_human_balance:.6f} {symbol})", fg="blue")
    
    escrow = get_payment(escrow_id_bytes, bridge)

    click.secho("\n=== Final Escrow Payment Details ===", bold=True)

    escrow['requestedAmount'] = escrow.get("requestedAmount") / 1e6 if network == "base-sepolia" else escrow.get("requestedAmount") / 1e18
    escrow['requestedAmountUsd'] = escrow.get("requestedAmountUsd") / 1e6

    escrow['postedAmount'] = escrow.get("postedAmount") / 1e6 if network == "base-sepolia" else escrow.get("postedAmount") / 1e18
    escrow['postedAmountUsd'] = escrow.get("postedAmountUsd") / 1e6
    escrow["escrow_id"] = escrow_id
    escrow["network"] = network

    cache.set("last_salt", salt)
    cache.set("last_settlement_id", settlement_id)
    cache.set("last_escrow_id", escrow_id)

    click.echo(json.dumps(escrow, indent=4))

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of BDAG/USDC you wish to receive.")
@click.option("--network", default="blockdag-testnet", type=click.Choice(SUPPORTED_NETWORKS), help="Blockchain network to use.")
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
    click.secho("\n=== Initialize Escrow ===", bold=True)
    GATEWAY = BLOCKDAG_TESTNET_GATEWAY_URL if network == "blockdag-testnet" else BASE_SEPOLIA_GATEWAY_URL
    EXPL_URL = "https://sepolia-explorer.base.org/tx/" if network == "base-sepolia" else "https://primordial.bdagscan.com/tx/"

    click.echo(f"Initializing escrow on {network} for amount: {amount}...")

    try:
        w3 = Web3(Web3.HTTPProvider(GATEWAY))
        account = w3.eth.account.from_key(private_key)
        click.secho(f"Using account: {account.address}", fg="blue")
    except Exception as e:
        raise ValueError(f"❌ Error setting up Web3 or account: {e}")
    
    if not is_chainsettle_api_running():
        click.secho("⚠️ Warning: ChainSettle API is not reachable, but can proceed onchain.", fg="yellow")

    if not recipient:
        recipient = account.address

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
    # max_escrow_time = bridge.functions.maxEscrowTime().call()

    recipient_email = bridge.functions.recipientEmail().call()
    click.echo(f"> EscrowBridge PayPal Recipient = {recipient_email}")

    # 1) Check the “minPaymentAmount” and “maxPaymentAmount” (these are stored as raw USDC units)
    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()

    # 2) Fetch the USDC token address that the ramp contract expects
    try:
        usdc_address = bridge.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)

        # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
        token_decimals = erc20.functions.decimals().call()
        symbol = "USDC"
        token_address = usdc_address
    except Exception as e:
        # print("❌ Error fetching token details:", e)
        token_decimals = 18
        symbol = "BDAG"
        token_address = ZERO_ADDRESS
        erc20 = None
    click.echo(f"> EscrowBridge Asset = {token_address} ({symbol})")

    fee = bridge.functions.fee().call()
    # print(f"> EscrowBridge.fee() = {fee} {symbol}")

    FEE_DENOMINATOR = bridge.functions.FEE_DENOMINATOR().call()
    # print(f"> EscrowBridge.FEE_DENOMINATOR() = {FEE_DENOMINATOR}")

    fee_percent = fee / FEE_DENOMINATOR
    click.echo(f"> EscrowBridge → fee percentage = {fee_percent * 100:.2f}%")

    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)
    # print(f"> EscrowBridge.minPaymentAmount() (human) = {min_human:.6f}")
    # print(f"> EscrowBridge.maxPaymentAmount() (human) = {max_human:.6f}")

    # 6) Validate the user‐supplied “amount”
    if amount < min_human or amount > max_human:
        raise ValueError(
            f"❌ Requested amount {amount} {symbol} is out of bounds: "
            f"minimum = {min_human:.6f} {symbol}, maximum = {max_human:.6f} {symbol}"
        )

    amount_raw = int(amount * (10 ** token_decimals))  # Convert to raw units

    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    bridge_human_balance = bridge_raw_balance / (10 ** token_decimals)  

    ramp_usdc_balance = bridge.functions.getFreeBalance().call()
    human_ramp_balance = ramp_usdc_balance / (10 ** token_decimals)
    # print(f"> EscrowBridge {symbol} balance (raw) = {ramp_usdc_balance}")
    # print(f"  → in human {symbol} = {human_ramp_balance:.6f} {symbol}")

    # print(f"> EscrowBridge {symbol} balance (raw) = {bridge_raw_balance}  → (≈{bridge_human_balance:.6f} {symbol})")
    # print(f" EscrowBridge free balance: (≈{human_ramp_balance:.6f} {symbol})")

    if amount > human_ramp_balance:
        raise ValueError(
            f"❌ Requested amount {amount} {symbol} exceeds available funds "
            f"(≈{human_ramp_balance:.6f} {symbol})"
        )
    
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

    click.secho(f"> Computed escrow_id = {escrow_id}", fg="blue")

    base_tx = bridge.functions.initPayment(
        escrow_id_bytes,
        amount_raw,
        recipient
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, 'pending'),
    })
    gas_est = w3.eth.estimate_gas(base_tx)
    gas_est_scaled = int(gas_est * gas_estimate_factor)  # Add buffer

    balance = w3.eth.get_balance(account.address)
    click.echo(f"Account balance: {w3.from_wei(balance, 'ether')} ETH")

    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
    priority_fee = w3.to_wei(2, "gwei")
    max_fee = base_fee + priority_fee

    est_cost = gas_est_scaled * max_fee
    click.echo(f"Estimated gas: {w3.from_wei(est_cost, 'ether')} ETH")

    if balance < est_cost:
        if not force:
            raise ValueError(
                f"❌ Insufficient ETH for estimated gas. "
                f"Balance = {w3.from_wei(balance, 'ether')} ETH, "
                f"Required ≈ {w3.from_wei(est_cost, 'ether')} ETH"
            )
        else:
            click.secho("⚠️ Warning: Insufficient ETH for estimated gas, but proceeding due to --force flag.", fg="red")

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
        raise Exception("❌ EscrowBridge.initPayment(...) reverted")

    click.secho(f"✓ initPayment({escrow_id}, {amount:.6f} {symbol}) submitted → Tx: {'0x' + h_init.hex()}", fg="green")
    click.secho(f"→ View on Explorer: {EXPL_URL}{'0x' + h_init.hex()}", fg="blue")

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

    click.secho("Escrow initialized successfully. Details:", bold=True)
    for key, value in info.items():
        click.echo(f"  {key}: {value}")

@click.command()
@click.option("--salt", default = None, help="The salt used in the escrow initialization.")
@click.option("--settlement-id", default = None,  help="The settlement ID used in the escrow initialization.")
def register_settlement(salt, settlement_id):
    click.secho("\n=== Register Escrow ===", bold=True)
    click.echo("Registering offchain data with the ChainSettle oracle...")
    if not is_chainsettle_api_running():
        raise ValueError("⚠️ Warning: ChainSettle API is not reachable. Off-chain registration will fail.")
    
    # Use global if not passed as argument
    if salt is None:
        salt = cache.get("last_salt")
        if not salt:
            raise ValueError("❌ No salt provided and no cached salt found.")

    if settlement_id is None:
        settlement_id = cache.get("last_settlement_id")
        if not settlement_id:
            raise ValueError("❌ No settlement ID provided and no cached settlement_id found.")
                
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
        click.secho(f"✅ User URL: {resp['settlement_info']['user_url']}", fg="green")
        webbrowser.open(resp['settlement_info']['user_url'])
    else:
        click.secho("⚠️ User URL not found in response.", fg="yellow")

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
    click.secho("\n=== Settle Escrow ===", bold=True)
    click.echo("Settling escrow onchain...")

    # Use global if not passed as argument
    if escrow_id is None:
        escrow_id = cache.get("last_escrow_id")
        if not escrow_id:  
            raise ValueError("❌ No escrow ID provided and no cached escrow_id found.")
        
    escrow_id_bytes = Web3.to_bytes(hexstr=escrow_id)

    network, bridge = find_network_for_settlement(escrow_id)
    if not network:
        raise ValueError(f"❌ Could not find network for escrow ID {escrow_id}")
    
    is_settled = bridge.functions.isSettled(escrow_id_bytes).call()
    if is_settled:
        click.secho(f"⚠️ Escrow ID {escrow_id} is already settled on {network}.", fg="yellow")
        return

    GATEWAY = BLOCKDAG_TESTNET_GATEWAY_URL if network == "blockdag-testnet" else BASE_SEPOLIA_GATEWAY_URL
    EXPL_URL = "https://sepolia-explorer.base.org/tx/" if network == "base-sepolia" else "https://primordial.bdagscan.com/tx/"
    click.secho(f"Settling escrow ID: {escrow_id} on network: {network}...", fg="blue")
    try:
        w3 = Web3(Web3.HTTPProvider(GATEWAY))
        account = w3.eth.account.from_key(private_key)
    except Exception as e:
        raise ValueError(f"❌ Error setting up Web3 or account: {e}")
    
    # contract_address = escrow_bridge_config[network]['address']
    # bridge_abi = escrow_bridge_config[network]['abi']

    # bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)

    base_tx = bridge.functions.settlePayment(escrow_id_bytes).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
    })

    try:
        gas_est = w3.eth.estimate_gas(base_tx)
    except Exception as e:
        gas_est = 200000
        click.echo("❌ Error estimating gas:", e)

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
        click.secho(f"✅ Payment settled: {EXPL_URL}{'0x' + tx_hash.hex()}", fg="green")
    else:
        click.secho(f"❌ Transaction failed: {EXPL_URL}{'0x' + tx_hash.hex()}", fg="red")

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