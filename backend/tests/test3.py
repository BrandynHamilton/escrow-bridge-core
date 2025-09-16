import webbrowser
from escrow_bridge import network_func, generate_salt
import os
from typing import Dict, Optional, List
from web3 import Web3

from dotenv import load_dotenv
import time
import json
import requests

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Load configuration and ABI paths
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, 'chainsettle_config.json')
artifact_path = os.path.join(BASE_DIR, '..', 'contracts', 'out', 'EscrowBridgeETH.sol', 'EscrowBridgeETH.json')

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

with open(artifact_path, "r") as f:
    ramp_abi = json.load(f)['abi']

MAX_256 = 2**256 - 1

SETTLEMENT_RAMP_ADDRESS = os.getenv('ESCROW_BRIDGE_ETH_ADDRESS')
ESCROW_BRIDGE_BLOCKDAG_ADDRESS_BDAG = os.getenv('ESCROW_BRIDGE_BLOCKDAG_ADDRESS_BDAG')
print(f"Using SettlementRamp address: {SETTLEMENT_RAMP_ADDRESS}")

THIRD_PARTY_KEY = os.getenv('THIRD_PARTY_KEY')
LISTENER_URL = os.getenv('LISTENER_URL')

def poll_settlement_status_onchain(ramp_contract, id_hash, max_attempts=60, delay=5):
    """
    Polls the on-chain settlement status every 5 seconds for up to 5 minutes (default).
    Exits early if the status reaches 3 (Confirmed) or 4 (Failed).
    """
    print(f"Polling settlement status for idHash: {id_hash.hex()} ...")
    for attempt in range(1, max_attempts + 1):
        # Fetch on-chain status
        status = ramp_contract.functions.getSettlementStatus(id_hash).call()
        print(f"[Attempt {attempt}] status: {status}")
        
        # If status is Confirmed (3) or Failed (4), exit early
        if status in [3, 4]:
            print(f"Settlement finalized with status: {status}")
            break
        
        # Wait before next attempt
        time.sleep(delay)
    else:
        print("Polling timed out after 5 minutes.")

def main(amount: float, settlement_id: Optional[str] = None,):
    """
    1) Connect to Base
    2) Check SettlementRamp’s USDC balance (in raw units)
       • If contract < required_amount: top up by calling ERC20.approve + SettlementRamp.fundEscrow
    3) Call initPayment(...) on SettlementRamp
    4) Store salt, then poll for finalization
    """

    if not settlement_id:
        settlement_id = secrets.token_hex(4)

    network = 'blockdag'

    if network == 'blockdag':
        contract_address = ESCROW_BRIDGE_BLOCKDAG_ADDRESS_BDAG
    else:
        contract_address = SETTLEMENT_RAMP_ADDRESS
    settlement_type = 'paypal'
    PRIVATE_KEY = os.getenv('EVM_PRIVATE_KEY')
    ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
    registry_address = config[network]['registry_addresses'][settlement_type]
    REGISTRY_ADDRESS = registry_address
    registry_abi = config[network]['abis'][settlement_type]

    EXPL_URL = config[network]['explorer_url']
    w3, account = network_func(
        network=network,
    )

    third_party_w3, third_party_account = network_func(
        network=network,
    )

    print(f'Third Party EOA = {third_party_account.address}')

    settlement_registry = w3.eth.contract(address=registry_address, abi=registry_abi)

    # ─────────────────────────────────────────────────────────────────────────
    # Instantiate the SettlementRamp contract
    # ─────────────────────────────────────────────────────────────────────────
    ramp = w3.eth.contract(address=contract_address, abi=ramp_abi)
    print(f"Using EOA = {account.address}")

    third_party_ramp = third_party_w3.eth.contract(
        address=contract_address, abi=ramp_abi
    )

    # settlement_reg_address = config[network]['registry_addresses']['SettlementRegistry']
    onchain_reg_address = ramp.functions.settlementRegistry().call()
    print(f"SettlementRamp.settlementRegistry() = {onchain_reg_address}")   
    print(f"Config settlementRegistry = {REGISTRY_ADDRESS}")
    if REGISTRY_ADDRESS.lower() != onchain_reg_address.lower():
        raise Exception(
            f"❌ SettlementRamp.settlementRegistry() = {onchain_reg_address} "
            f"does not match config value {REGISTRY_ADDRESS}."
        )

    # 1) Check the “minPaymentAmount” and “maxPaymentAmount” (these are stored as raw USDC units)
    min_raw = ramp.functions.minPaymentAmount().call()
    max_raw = ramp.functions.maxPaymentAmount().call()
    print(f"> SettlementRamp.minPaymentAmount() (raw) = {min_raw}")
    print(f"> SettlementRamp.maxPaymentAmount() (raw) = {max_raw}")

    # 2) Fetch the USDC token address that the ramp contract expects

    # Fee
    fee = ramp.functions.fee().call()
    print(f"> SettlementRamp.fee() = {fee / 10000} ")

    # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
    token_decimals = 18

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

    # 7) Fetch SettlementRamp.recipientEmail() just to confirm we are talking to the right contract
    recipient_email = ramp.functions.recipientEmail().call()
    print(f"> SettlementRamp.recipientEmail() = {recipient_email}")

    # 8) Calculate the “raw” integer we need to pass into initPayment(...)
    #    raw_amount_needed = amount × (10 ** token_decimals)
    raw_amount_needed = int(amount * (10 ** token_decimals))
    print(f"> Converting {amount:.6f} USDC → raw = {raw_amount_needed}")

    # 9) Check SettlementRamp’s current USDC balance (in raw units)
    ramp_usdc_balance = ramp.functions.getFreeBalance().call()
    human_ramp_balance = ramp_usdc_balance / (10 ** token_decimals)
    print(f"> SettlementRamp USDC balance (raw) = {ramp_usdc_balance}")
    print(f"  → in human USDC = {human_ramp_balance:.6f} USDC")

    # 10) If SettlementRamp’s balance < raw_amount_needed, top up the difference:
    if ramp_usdc_balance < raw_amount_needed:
        top_up = raw_amount_needed - ramp_usdc_balance
        print(f"→ Ramp contract needs an additional {top_up} raw USDC units "
              f"(≈ {top_up / (10**token_decimals):.6f} USDC).")

        # 10.a) Check our EOA’s own USDC balance
        owner_raw_balance = w3.eth.get_balance(account.address)
        owner_human_balance = owner_raw_balance / (10 ** token_decimals)
        print(f"> EOA USDC balance (raw) = {owner_raw_balance}  → (≈{owner_human_balance:.6f} USDC)")

        if owner_raw_balance < top_up:
            raise Exception(
                f"❌ EOA’s USDC ({owner_human_balance:.6f} USDC) is less than required "
                f"{top_up / (10**token_decimals):.6f} USDC."
            )
        
        base_nonce = w3.eth.get_transaction_count(account.address, "pending")
        latest_block = third_party_w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
        priority_fee = w3.to_wei(2, "gwei")
        max_fee = base_fee + priority_fee
        
        tx = {
            "from": account.address,
            "to": contract_address,
            "value": top_up,
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2,
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

    else:
        print("✓ SettlementRamp already has sufficient USDC.")

    time.sleep(5)  # Wait for the fund transaction to be mined

    eth_balance = w3.eth.get_balance(contract_address)
    human_ramp_balance = eth_balance / (10 ** token_decimals)
    print(f"> SettlementRamp USDC balance (raw) = {eth_balance}  → (≈{human_ramp_balance:.6f} USDC)")
    print(f"  → in human USDC = {human_ramp_balance:.6f} USDC")

    if eth_balance < raw_amount_needed:
        raise Exception(
            f"❌ SettlementRamp only holds {eth_balance} raw units, "
            f"but payer needs {raw_amount_needed}."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 11) Now that the contract is funded, call initPayment(...)
    # This step can be done in web3.js in the frontend, but we do it here
    # for demonstration purposes.
    # ─────────────────────────────────────────────────────────────────────────
    salt = generate_salt()
    print(f"> Generated salt = {salt}")
    if not salt.startswith("0x"):
        salt_hex = "0x" + salt

    salt_bytes = bytes.fromhex(salt_hex[2:])
    settlement_id_bytes = settlement_id.encode('utf-8')  

    if not salt.startswith("0x"):
            salt = "0x" + salt

    # 2) Compute the same keccak256(abi.encodePacked(salt, settlementId))    
    id_hash_bytes = w3.solidity_keccak(
        ["bytes32", "string"],
        [salt, settlement_id]
    )

    id_hash = id_hash_bytes.hex()
    print(f"> Computed id_hash = {id_hash}")

    print(f'raw_amount_needed = {raw_amount_needed} (≈ {amount:.6f} USDC)')

    # balance = erc20.functions.balanceOf(third_party_account.address).call()
    # human_balance = balance / (10 ** token_decimals)
    # print(f"User's USDC balance before settlement: {balance} raw units "
    #       f"(≈ {human_balance:.6f} USDC)")
    
    # # 11.a) Check if the user has enough USDC to cover the settlement
    # if balance < raw_amount_needed:
    #     raise Exception(
    #         f"❌ User's USDC balance ({human_balance:.6f} USDC) is less than required "
    #         f"{amount:.6f} USDC ({raw_amount_needed} raw units).")

    time.sleep(5)  # Wait for the approval to be mined
          
    base_tx = third_party_ramp.functions.initPayment(
        id_hash_bytes,
        raw_amount_needed
    ).build_transaction({
        "from": third_party_account.address,
        "nonce": third_party_w3.eth.get_transaction_count(third_party_account.address),
    })
    gas_est = third_party_w3.eth.estimate_gas(base_tx)
    latest_block = third_party_w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
    priority_fee = third_party_w3.to_wei(2, "gwei")
    max_fee = base_fee + priority_fee

    base_tx.update({
        "gas": int(gas_est * 1.2),
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": max_fee,
        "type": 2
    })
    signed_init = third_party_account.sign_transaction(base_tx)
    h_init = third_party_w3.eth.send_raw_transaction(signed_init.raw_transaction)
    receipt_init = third_party_w3.eth.wait_for_transaction_receipt(h_init)
    if receipt_init.status != 1:
        raise Exception("❌ SettlementRamp.initPayment(...) reverted")

    print(f"✓ initPayment({settlement_id}, {amount:.6f} USDC) submitted → Tx: {h_init.hex()}")
    print(f"→ View on Explorer: {EXPL_URL}{'0x' + h_init.hex()}")

    totalEscrowed = ramp.functions.totalEscrowed().call()
    print(f"SettlementRamp.totalEscrowed() = {totalEscrowed} raw USDC ")

    # ─────────────────────────────────────────────────────────────────────────
    # 12) Store salt off‐chain, then poll for settlement to finalize.
    # The frontend would need to do this, but we do it here for demonstration.
    # Note: The ChainSettleService is a wrapper around the ChainSettle API.
    # ─────────────────────────────────────────────────────────────────────────
    payload = {
        "id_hash": id_hash,
        "salt": salt_hex,
        "settlement_id": settlement_id,
        "recipient_email": recipient_email,
    }
    print(f'payload: {payload}')
    r = requests.post(f"{os.getenv('CHAINSETTLE_API_URL')}/settlement/register_settlement", 
                     json=payload)
    r.raise_for_status()
    resp = r.json()
    if 'user_url' in resp.get('settlement_info', {}):
        print(f"✓ User URL: {resp['settlement_info']['user_url']}")
        webbrowser.open(resp['settlement_info']['user_url'])
    else:
        print("⚠️ User URL not found in response.")

    # chainsettle = ChainSettleService()

    # resp = chainsettle.store_salt(
    #     id_hash=id_hash,
    #     salt=salt_hex,
    #     email=user_email,
    #     recipient_email=recipient_email,
    # )
    print(f"✓ Registered Offchain: {json.dumps(resp, indent=2)}")

    # We can also poll settlement activity directly in the smart contract
    def status(escrowId, max_attempts=60, delay=5):
        print(f"Received status request with data: {escrowId}")
        
        if escrowId.startswith("0x"):
            escrowId = escrowId[2:]

        print(f"Processing escrowId: {escrowId}")
        
        id_hash_bytes = Web3.to_bytes(hexstr=escrowId)

        for attempt in range(1, max_attempts + 1):
            print(f"[Attempt {attempt}] Checking status for {escrowId}...")
            completed_escrows = ramp.functions.getCompletedEscrows().call({"from": account.address})
            # status = ramp.functions.getSettlementStatus(id_hash_bytes).call({"from": account.address})

            if id_hash_bytes in completed_escrows:
                break
            else:
                time.sleep(delay)
                continue

    old_balance = w3.eth.get_balance(third_party_account.address)
    old_human_balance = old_balance / (10 ** token_decimals)
    print(f"User's USDC balance before settlement: {old_balance} raw units "
          f"(≈ {old_human_balance:.6f} USDC)")
   
    status(id_hash)

    new_balance = w3.eth.get_balance(third_party_account.address)
    new_human_balance = new_balance / (10 ** token_decimals)
    print(f"User's USDC balance after settlement: {new_balance} raw units "
          f"(≈ {new_human_balance:.6f} USDC)")

    return "Done."

if __name__ == "__main__":
    import secrets
    print("Running Escrow Bridge Test")
    # settlement_id = secrets.token_hex(4) # Generate a random settlement ID
    amount = 1  # Amount in USDC to settle
    main(
        # settlement_id=settlement_id,
        amount=amount,
    )
