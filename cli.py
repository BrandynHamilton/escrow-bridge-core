import click
from web3 import Web3   
import os
from dotenv import load_dotenv
import json
import secrets
import time
import requests
from escrow_bridge import network_func

load_dotenv()

ABI_PATH = os.path.join('backend', 'abi', 'escrowBridgeAbi.json')
ERC20_ABI_PATH = os.path.join('backend', 'abi', 'erc20Abi.json')

@click.command()
@click.option('--amount', type=int, help='Amount of USDC to request')
@click.option('--recipient-address', type=str, required=False, help='Recipient address for the USDC, Defaults to msg.sender address')
@click.option('--email', type=str, help='User email for the request')
def main(amount, recipient_address, email):
    """
    Main function to handle the CLI commands for the Escrow Bridge.
    Enables users to request USDC by providing the amount, recipient address, and email.
    If recipient address is not provided, it defaults to the sender's address.

    Usage: python cli.py --amount <amount> --recipient <recipient> --email <email>
    Example: python cli.py --amount 1000 --recipient 0xRecipientAddress --email joe@gmail.com
    """
    if not amount or not email:
        click.echo("Please provide all required parameters: amount, email.")
        return
    
    # Load environment variables
    ESCROW_BRIDGE_ADDRESS = os.getenv('ESCROW_BRIDGE_ADDRESS', "0xe2241a04c7347FD6571979b1F4a41C267fcf1A15")  # Default provided
    PRIVATE_KEY = os.getenv('PRIVATE_KEY')
    ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
    CHAINSETTLE_API = os.getenv('CHAINSETTLE_API', "https://app.chainsettle.tech")  # Default provided

    missing_vars = []

    if not ESCROW_BRIDGE_ADDRESS:
        missing_vars.append('ESCROW_BRIDGE_ADDRESS')
    if not PRIVATE_KEY:
        missing_vars.append('PRIVATE_KEY')
    if not ALCHEMY_API_KEY:
        missing_vars.append('ALCHEMY_API_KEY')
    if not CHAINSETTLE_API:
        missing_vars.append('CHAINSETTLE_API')

    if missing_vars:
        click.echo(f"Missing required environment variable(s): {', '.join(missing_vars)}")
        return  # Or sys.exit(1) if not inside a function
    
    try:
        # Initialize Web3 connection
        w3, account = network_func(
            network='base',
            ALCHEMY_API_KEY=ALCHEMY_API_KEY,
            PRIVATE_KEY=PRIVATE_KEY
        )
    except Exception as e:
        click.echo(f"Error connecting to the network: {e}")
    
    # Load the Escrow Bridge contract
    with open(ABI_PATH, 'r') as f:
        bridge_abi = json.load(f)
    
    # Load the ERC20 ABI
    with open(ERC20_ABI_PATH, 'r') as f:
        erc20_abi = json.load(f)

    bridge = w3.eth.contract(address=ESCROW_BRIDGE_ADDRESS, abi=bridge_abi)

    if not recipient_address:
        recipient_address = account.address

    click.echo(f"Requesting {amount} USDC for {recipient_address} with email {email}.")

    # 1) Check the “minPaymentAmount” and “maxPaymentAmount” (these are stored as raw USDC units)
    min_raw = bridge.functions.minPaymentAmount().call()
    max_raw = bridge.functions.maxPaymentAmount().call()
    print(f"> EscrowBridge.minPaymentAmount() (raw) = {min_raw}")
    print(f"> EscrowBridge.maxPaymentAmount() (raw) = {max_raw}")

    # 2) Fetch the USDC token address that the EscrowBridge contract expects
    usdc_address = bridge.functions.usdcToken().call()
    print(f"> EscrowBridge.usdcToken() = {usdc_address}")

    # Recipient email for PayPal payment
    recipient_email = bridge.functions.recipientEmail().call()
    print(f"> EscrowBridge.recipientEmail() = {recipient_email}")

    # Fee
    fee = bridge.functions.fee().call()
    print(f"> EscrowBridge.fee() = {fee / 10000} ")

    # 3) Instantiate a minimal ERC20 handle so we can call decimals() and balanceOf() etc.
    erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)

    # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
    token_decimals = erc20.functions.decimals().call()
    print(f"> ERC20.decimals() = {token_decimals}")

    # 5) Convert min_raw and max_raw (which are “uint raw units”) → human USDC floats:
    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)
    print(f"  → in human USDC: min = {min_human:.6f}, max = {max_human:.6f} ")

    # 6) Validate the user‐supplied “amount”
    if amount < min_human or amount > max_human:
        raise ValueError(
            f"❌ Requested amount {amount} USDC is out of bounds: "
            f"minimum = {min_human:.6f} USDC, maximum = {max_human:.6f} USDC"
        )

    # 7) Calculate the “raw” integer we need to pass into initPayment(...)
    raw_amount_needed = int(amount * (10 ** token_decimals))
    print(f"> Converting {amount:.6f} USDC → raw = {raw_amount_needed}")

    # 8) Check EscrowBridge current USDC balance (in raw units)
    bridge_usdc_balance = bridge.functions.getFreeBalance().call()
    human_bridge_balance = bridge_usdc_balance / (10 ** token_decimals)
    print(f"> EscrowBridge USDC balance (raw) = {bridge_usdc_balance}")
    print(f"  → in human USDC = {human_bridge_balance:.6f} USDC")

    # 9) If EscrowBridge's balance < raw_amount_needed, top up the difference:
    if bridge_usdc_balance < raw_amount_needed:
        click.echo(
            f"❌ Escrow Bridge USDC balance ({human_bridge_balance:.6f} USDC) "
            f"is less than the requested amount ({amount:.6f} USDC). "
            "Owner needs to top up the contract."
        )
        raise ValueError(
            "Escrow Bridge USDC balance is insufficient for the requested amount."
        )
    
    time.sleep(5)

    settlement_id = secrets.token_hex(4) # Generate a random settlement ID
    print(f"> Generated settlement ID = {settlement_id}")

    salt = os.urandom(32).hex() # Generate a random salt

    print(f"> Generated salt = {salt}")
    if not salt.startswith("0x"):
        salt = "0x" + salt

    id_hash_bytes = w3.solidity_keccak(
        ["bytes32", "string"],
        [salt, settlement_id]
    )

    email_hash_bytes = w3.solidity_keccak(
        ["bytes32", "string"],
        [salt, email]
    )

    id_hash = id_hash_bytes.hex()
    print(f"> Computed id_hash = {id_hash}")

    before_balance = erc20.functions.balanceOf(recipient_address).call()
    human_before_balance = before_balance / (10 ** token_decimals)

    native_balance = w3.eth.get_balance(account.address)
    print(f"Your native ETH balance: {w3.from_wei(native_balance, 'ether'):.6f} ETH")

    base_tx = bridge.functions.initPayment(
        id_hash_bytes,
        email_hash_bytes,
        raw_amount_needed,
        recipient_address
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
    })

    gas_est = w3.eth.estimate_gas(base_tx)
    gas_est = int(gas_est * 1.2)  # Add a buffer to the gas estimate
    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
    priority_fee = w3.to_wei(2, "gwei")
    max_fee = base_fee + priority_fee

    if native_balance < max_fee * gas_est:
        raise ValueError(
            f"❌ Insufficient native ETH balance for gas fees. "
            f"Required: {w3.from_wei(max_fee * gas_est, 'ether'):.6f} ETH, "
            f"Available: {w3.from_wei(native_balance, 'ether'):.6f} ETH"
        )

    base_tx.update({
        "gas": gas_est,
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": max_fee,
        "type": 2
    })
    signed_init = account.sign_transaction(base_tx)
    h_init = w3.eth.send_raw_transaction(signed_init.raw_transaction)
    receipt_init = w3.eth.wait_for_transaction_receipt(h_init)
    if receipt_init.status != 1:
        raise Exception("❌ EscrowBridge.initPayment(...) reverted")

    print(f"✓ initPayment({settlement_id}, {amount:.6f} USDC) submitted → Tx: {h_init.hex()}")
    print(f"→ View on Explorer: https://sepolia.basescan.org/tx/{'0x'+h_init.hex()}")

    # 10) Store the salt and other offchain data in the web3 oracle backend service
    print("Storing salt and payment details in the web3 oracle backend service...")

    r = requests.post(url=F"{CHAINSETTLE_API}/api/store_salt", json={
        "id_hash": id_hash,
        "email": email,
        "amount": amount,
        "recipient_email": recipient_email,
        "salt": salt
    })

    r.raise_for_status()
    if r.status_code == 200:
        print("Salt stored successfully.")
    else:
        print(f"Failed to store salt: {r.status_code} - {r.text}")

    totalEscrowed = bridge.functions.totalEscrowed().call()
    print(f"EscrowBridge.totalEscrowed() = {totalEscrowed} raw USDC ")
    print(f"  → in human USDC = {totalEscrowed / (10 ** token_decimals):.6f} USDC")

    # Polling for escrow status

    for i in range(60):
        print(f"Polling for escrow status... Attempt {i + 1}/60")
        print(f"Check {email} inbox for PayPal sandbox payment instructions.")
        time.sleep(5)

        pending_escrows = bridge.functions.getPendingEscrows().call({"from": account.address})
        completed_escrows = bridge.functions.getCompletedEscrows().call({"from": account.address})

        if id_hash_bytes in pending_escrows:
            status = "pending"
            print(f"Escrow {id_hash} is {status}.")
        elif id_hash_bytes in completed_escrows:
            status = "completed"
            print(f"Escrow {id_hash} is {status}.")
            break
        else:
            status = "not found"
            print(f"Escrow {id_hash} not found in pending or completed escrows.")
            raise Exception(
                f"Escrow {id_hash} not found in pending or completed escrows."
            )
        
    # 11) Check the recipient USDC balance before and after the transaction
    print(f"{recipient_address} USDC balance before: {human_before_balance:.6f} USDC")
    # Fetch the recipient USDC balance
    balance = erc20.functions.balanceOf(recipient_address).call()
    human_balance = balance / (10 ** token_decimals)
    print(f"{recipient_address} USDC balance: {human_balance:.6f} USDC")

if __name__ == '__main__':
    main()