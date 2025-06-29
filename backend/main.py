from flask import Flask, request
from web3 import Web3
import threading
import time
import os
import json
from dotenv import load_dotenv
from chainsettle_sdk import ChainSettleService
from escrow_bridge import network_func
from threading import Thread, Lock
from flask_cors import CORS

load_dotenv()

active_threads = set()
lock = Lock()

# Load ABI and config
ABI_PATH = os.path.join('abi', 'escrowBridgeAbi.json')
with open(ABI_PATH, 'r') as f:
    ramp_abi = json.load(f)

CONFIG_PATH = os.path.join('chainsettle_config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

SETTLEMENT_RAMP_ADDRESS = os.getenv('ESCROW_BRIDGE_ADDRESS')
PRIVATE_KEY = os.getenv('EVM_PRIVATE_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
network = 'base'
w3, account = network_func(
    network=network,
    ALCHEMY_API_KEY=ALCHEMY_API_KEY,
    PRIVATE_KEY=PRIVATE_KEY
)

ramp = w3.eth.contract(address=SETTLEMENT_RAMP_ADDRESS, abi=ramp_abi)
chainsettle = ChainSettleService()

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
    
    return app

if __name__ == '__main__':
    print("Starting Settlement Listener...")
    t1 = threading.Thread(target=log_loop, daemon=True)
    t2 = threading.Thread(target=poll_pending_settlements, daemon=True)
    t1.start()
    t2.start()
    app = create_app()
    print("Flask app is starting...")
    app.run(host='0.0.0.0', port=4028)