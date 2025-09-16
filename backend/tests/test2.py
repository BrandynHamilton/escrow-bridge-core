from flask import Flask, request
from web3 import Web3
import threading
import time
import os
import json
from dotenv import load_dotenv
from escrow_bridge import network_func
from threading import Thread, Lock
from flask_cors import CORS
# from httpayer import X402Gate
from ccip_terminal import USDC_MAP
from chainsettle import generate_salt

load_dotenv()

active_threads = set()
lock = Lock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, 'chainsettle_config.json')
ABI_PATH = os.path.join(BASE_DIR, 'abi', 'escrowBridgeAbi.json')
ERC20_ABI = os.path.join(BASE_DIR, 'abi', 'erc20Abi.json')
# Load ABI and config
with open(ABI_PATH, 'r') as f:
    ramp_abi = json.load(f)

with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

with open(ERC20_ABI, 'r') as f:
    ERC20_ABI = json.load(f)

SETTLEMENT_RAMP_ADDRESS = os.getenv('ESCROW_BRIDGE_ADDRESS')
PRIVATE_KEY = os.getenv('EVM_PRIVATE_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
network = 'base'
w3, account = network_func(
    network=network,
)

FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org")
PAY_TO_ADDRESS = os.getenv("PAY_TO_ADDRESS", account.address)

print(f'FACILITATOR_URL: {FACILITATOR_URL}')

if network == 'avalanche':
    network_id = 'avalanche-fuji'
    if FACILITATOR_URL == "https://x402.org":
        raise ValueError("FACILITATOR_URL must be set to a valid URL for Avalanche Fuji testnet.")  
elif network == 'base':
    network_id = 'base-sepolia'
    if FACILITATOR_URL != "https://x402.org":
        raise ValueError("FACILITATOR_URL must be set to a valid URL for Base Sepolia testnet.")

# token_address = USDC_MAP.get(network)

# token_contract = w3.to_checksum_address(token_address)
# token = w3.eth.contract(address=token_contract, abi=ERC20_ABI)
# name_onchain    = token.functions.name().call()
# version_onchain = token.functions.version().call() 

# extra = {"name": name_onchain, "version": version_onchain}

# print(f'Network: {network}, Network ID: {network_id}, extra: {extra}')

# gate = X402Gate(
#     pay_to=PAY_TO_ADDRESS,
#     network=network_id,
#     asset_address=token_address,
#     max_amount=1000,
#     asset_name=extra["name"],
#     asset_version=extra["version"],
#     facilitator_url=FACILITATOR_URL
# )

ramp = w3.eth.contract(address=SETTLEMENT_RAMP_ADDRESS, abi=ramp_abi)

pending_ids = set()

def handle_event(event):
    print(f"New event detected: {event.event}")
    id_hash = event['args']['escrowId'].hex()
    print(f"Detected PaymentInitialized event: {id_hash}")
    pending_ids.add(id_hash)

def poll_pending_settlements():
    while True:
        for id_hash in list(pending_ids):
            with lock:
                if id_hash in active_threads:
                    continue
                active_threads.add(id_hash)

            def _poll_and_finalize(id_hash_inner):
                try:
                    print(f"Polling ChainSettle for {id_hash_inner}")
                    id_hash_bytes = Web3.to_bytes(hexstr=id_hash_inner)
                    chainsettle.poll_settlement_status_onchain(ramp, id_hash_bytes, max_attempts=60, delay=5) 
                    print(f"Finalizing payment for {id_hash_inner}")

                    base_tx = ramp.functions.settlePayment(id_hash_bytes).build_transaction({
                        "from": account.address,
                        "nonce": w3.eth.get_transaction_count(account.address),
                    })

                    gas_est = w3.eth.estimate_gas(base_tx)
                    print(f"Gas estimate for settlePayment: {gas_est} units")

                    latest_block = w3.eth.get_block("latest")
                    base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
                    priority_fee = w3.to_wei(2, "gwei")
                    max_fee = base_fee + priority_fee

                    base_tx.update({
                        "gas": int(gas_est * 1.2),
                        "maxPriorityFeePerGas": priority_fee,
                        "maxFeePerGas": max_fee,
                        "type": 2
                    })

                    signed_tx = account.sign_transaction(base_tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                    if receipt.status == 1:
                        print(f"Payment settled: {tx_hash.hex()}")
                    else:
                        print(f"Transaction failed: {tx_hash.hex()}")
                except Exception as e:
                    print(f"Error settling {id_hash_inner}: {e}")
                finally:
                    with lock:
                        pending_ids.discard(id_hash_inner)
                        active_threads.discard(id_hash_inner)

            Thread(target=_poll_and_finalize, args=(id_hash,), daemon=True).start()

        time.sleep(2)
 
def log_loop():
    event_filter = ramp.events.PaymentInitialized.create_filter(from_block='latest')
    while True:
        for event in event_filter.get_new_entries():
            handle_event(event)
        time.sleep(5)

def create_app():

    app = Flask(__name__)

    CORS(app)

    @app.route("/")
    def home():
        return "Escrow Bridge Listener is Running"

    @app.route("/status", methods=['POST'])
    def status():
        data = request.get_json()
        escrowId = data.get("escrowId", "")
        print(f"Received status request with data: {escrowId}")
        if not escrowId:
            return {"error": "No data provided"}, 400
        
        if escrowId.startswith("0x"):
            escrowId = escrowId[2:]

        print(f"Processing escrowId: {escrowId}")
        
        id_hash_bytes = Web3.to_bytes(hexstr=escrowId)

        pending_escrows = ramp.functions.getPendingEscrows().call({"from": account.address})
        completed_escrows = ramp.functions.getCompletedEscrows().call({"from": account.address})
        # status = ramp.functions.getSettlementStatus(id_hash_bytes).call({"from": account.address})

        if id_hash_bytes in pending_escrows:
            return {"status": "pending", "message": "Pending settlement found."}, 200
        elif id_hash_bytes in completed_escrows:
            return {"status": "completed", "message": "Completed settlement found."}, 200
        else:
            return {"error": "Settlement not found."}, 404
        
    @app.route("/request_payment", methods=['POST'])
    def request_payment():
        import secrets
        data = request.get_json()
        print(f"Received payment request with data: {data}")
        if not data or 'amount' not in data or 'receiver' not in data:
            return {"error": "Invalid request data"}, 400
        
        amount = data['amount']
        receiver = data['receiver']
        email = data['email']
        api_key = data.get('api_key', None) # This is not used in the current implementation
        # api key would be used for additional validation or logging

        raw_amount_needed = amount * 10**6  # Assuming USDC has 6 decimals
        print(f"Raw amount needed: {raw_amount_needed}")

        settlement_id = secrets.token_hex(4)
        print(f"Generated settlement ID: {settlement_id}")

        salt = generate_salt()
        if not salt.startswith("0x"):
            salt = "0x" + salt

        print(f"Generated salt: {salt}")

        id_hash_bytes = w3.solidity_keccak(
            ["bytes32", "string"],
            [salt, settlement_id]
        )

        user_email_hash_bytes = w3.solidity_keccak(
            ["bytes32", "string"],
            [salt, email]
        )

        id_hash = id_hash_bytes.hex()
        print(f"> Computed id_hash = {id_hash}")

        recipient_email = ramp.functions.recipientEmail().call()

        if not Web3.is_checksum_address(receiver):
            return {"error": "Invalid receiver address"}, 400
        
        try:
        
            tx = ramp.functions.initPayment(
                id_hash_bytes,
                user_email_hash_bytes,
                raw_amount_needed,
                receiver
            ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            })
            gas_est = w3.eth.estimate_gas(tx)
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
            priority_fee = w3.to_wei(2, "gwei")
            max_fee = base_fee + priority_fee

            tx.update({
                "gas": int(gas_est * 1.2),
                "maxPriorityFeePerGas": priority_fee,
                "maxFeePerGas": max_fee,
                "type": 2
            })
            signed_init = account.sign_transaction(tx)
            h_init = w3.eth.send_raw_transaction(signed_init.raw_transaction)
            receipt_init = w3.eth.wait_for_transaction_receipt(h_init)
            if receipt_init.status != 1:
                raise Exception("SettlementRamp.initPayment(...) reverted")

            print(f"✓ initPayment({settlement_id}, {amount:.6f} USDC) submitted → Tx: {h_init.hex()}")

            # chainsettle = ChainSettleService()

            # chainsettle.store_salt(
            #     id_hash=id_hash,
            #     salt=salt,
            #     email=email,
            #     recipient_email=recipient_email,
            # )

            return {"tx_hash": h_init.hex(), "id_hash":id_hash}, 200
        except Exception as e:
            print(f"Error processing payment request: {e}")
            return {"error": str(e)}, 500

    return app

if __name__ == '__main__':
    print("Starting Settlement Listener...")
    t1 = threading.Thread(target=log_loop, daemon=True)
    t2 = threading.Thread(target=poll_pending_settlements, daemon=True)
    t1.start()
    t2.start()
    app = create_app()
    print("Flask app is starting...")
    app.run(host='0.0.0.0', port=4085)