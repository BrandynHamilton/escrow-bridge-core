from email.mime import base
from web3 import Web3
import threading, queue
import time
import os
import json
from dotenv import load_dotenv
from diskcache import Cache
import httpx
from escrow_bridge import network_func, get_payment, get_exchange_rate, SUPPORTED_NETWORKS, ZERO_ADDRESS
from threading import Thread, Lock
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import asyncio
from Crypto.Hash import keccak
from hexbytes import HexBytes
from apscheduler.schedulers.background import BackgroundScheduler
import json
import base64
import sqlite3
import hashlib
import pandas as pd
from chartengineer import ChartMaker
from plotly.utils import PlotlyJSONEncoder
from pydantic import BaseModel

load_dotenv()

cache = Cache("cache")

app = FastAPI(
    title="Escrow Bridge Listener API",
    description="Automatically generated OpenAPI docs",
    version="1.0"
)

templates = Jinja2Templates(directory="templates")

# Add CORS middleware
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allows requests from these origins
    allow_credentials=True,
    allow_methods=["*"],    # Allows all HTTP methods
    allow_headers=["*"],    # Allows all headers
)


class WebhookPayload(BaseModel):
    webhook_url: str
    escrowId: str

active_threads = set()
lock = Lock()

# Load ABI and config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
native_bridge_artifact_path = os.path.join(BASE_DIR, "..", "contracts", "out", "EscrowBridgeETH.sol", "EscrowBridgeETH.json")
token_bridge_artifact_path = os.path.join(BASE_DIR, "..", "contracts", "out", "EscrowBridge.sol", "EscrowBridge.json")

bdag_address_path = os.path.join(BASE_DIR, "..", "contracts", "deployments", "blockdag-escrow-bridge.json")
base_address_path = os.path.join(BASE_DIR, "..", "contracts", "deployments", "base-escrow-bridge.json")

print(f'Loading ABI from {native_bridge_artifact_path}')

# Relative path to save ABI
with open(native_bridge_artifact_path, 'r') as f:
    native_bridge_abi = json.load(f)['abi']

print(f'Loading ABI from {token_bridge_artifact_path}')
with open(token_bridge_artifact_path, 'r') as f:
    token_bridge_abi = json.load(f)['abi']

with open(bdag_address_path, 'r') as f:
    NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG = json.load(f)['deployedTo']

with open(base_address_path, 'r') as f:
    TOKEN_ESCROW_BRIDGE_ADDRESS_BASE = json.load(f)['deployedTo']

erc20_abi_path = os.path.join(BASE_DIR, 'abi', 'erc20Abi.json')
with open(erc20_abi_path, 'r') as f:
    erc20_abi = json.load(f)

CONFIG_PATH = os.path.join(BASE_DIR, 'chainsettle_config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

# NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG = os.getenv('NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG')
# TOKEN_ESCROW_BRIDGE_ADDRESS_BASE = os.getenv('TOKEN_ESCROW_BRIDGE_ADDRESS_BASE')

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

event_queue = queue.Queue()

PRIVATE_KEY = os.getenv('EVM_PRIVATE_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')

assert PRIVATE_KEY, "No PRIVATE_KEY in env"

bdag_w3, bdag_account = network_func(
    network='blockdag-testnet',
)

base_w3, base_account = network_func(
    network='base-sepolia',
)

base_contract = base_w3.eth.contract(address=TOKEN_ESCROW_BRIDGE_ADDRESS_BASE, abi=token_bridge_abi)
blockdag_contract = bdag_w3.eth.contract(address=NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG, abi=native_bridge_abi)

usdc_address = base_contract.functions.usdcToken().call()
erc20 = base_w3.eth.contract(address=usdc_address, abi=erc20_abi)
max_escrow_time = blockdag_contract.functions.maxEscrowTime().call()

fee = blockdag_contract.functions.fee().call()
FEE_DENOMINATOR = blockdag_contract.functions.FEE_DENOMINATOR().call()
fee_pct = f"{fee / FEE_DENOMINATOR * 100:.2f}%"

webhook_db_path = "webhooks.db"
data_analysis_path = "data_analysis.db"
pending_ids = set()

def escrow_worker():
    while True:
        event = event_queue.get()  # blocks until new event
        try:
            add_event(event)  # existing function
        except Exception as e:
            print("Escrow worker error:", e)
        finally:
            event_queue.task_done()

threading.Thread(target=escrow_worker, daemon=True).start()

async def poll_and_expire_escrows(interval=60):
    while True:
        for net in SUPPORTED_NETWORKS:
            if net == "blockdag-testnet":
                w3, account = bdag_w3, bdag_account
            else:
                w3, account = base_w3, base_account

            contract_address = escrow_bridge_config[net]['address']
            abi = escrow_bridge_config[net]['abi']
            contract = w3.eth.contract(address=contract_address, abi=abi)

            pending = contract.functions.getPendingEscrows().call()

            for escrow_id in pending:
                payment = contract.functions.payments(escrow_id).call()
                created_at = payment[8]  # Payment.createdAt
                if time.time() > created_at + max_escrow_time:
                    try:
                        base_tx = contract.functions.expireEscrow(escrow_id).build_transaction({
                            'from': account.address,
                            'nonce': w3.eth.get_transaction_count(account.address, 'pending'),
                        })
                        try:
                            gas_est = w3.eth.estimate_gas(base_tx)
                        except Exception as e:
                            gas_est = 200000
                            print("❌ Error estimating gas:", e)

                        latest_block = w3.eth.get_block("latest")
                        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
                        priority_fee = w3.to_wei(2, "gwei")
                        max_fee = base_fee + priority_fee

                        base_tx.update({
                            "gas": int(gas_est * 2),
                            "maxPriorityFeePerGas": priority_fee,
                            "maxFeePerGas": max_fee,
                            "type": 2
                        })

                        signed_tx = account.sign_transaction(base_tx)
                        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

                        if receipt.status == 1:
                            print(f"✅ Escrow expired: {tx_hash.hex()}")
                        else:
                            print(f"❌ Transaction failed: {tx_hash.hex()}")
                    except Exception as e:
                        print(f"❌ Failed to expire {escrow_id.hex()}: {e}")
        await asyncio.sleep(interval)

def create_charts():
    df = events_to_df()
    if df.empty:
        print("No events yet; returning empty charts")
        return json.dumps({}), json.dumps({})

    df.set_index("createdAt", inplace=True)
    df.index = pd.to_datetime(df.index)

    base_df = df[df["network"] == "base-sepolia"]
    blockdag_df = df[df["network"] == "blockdag-testnet"]

    if base_df.empty and blockdag_df.empty:
        print("No network-specific data yet; returning empty charts")
        return json.dumps({}), json.dumps({})

    cm1, cm2 = ChartMaker(shuffle_colors=False), ChartMaker(shuffle_colors=False)

    if not base_df.empty:
        cm1.build(
            df=base_df[['amountRequestedUsd']].resample('D').sum(),
            axes_data={'y1':['amountRequestedUsd']},
            title="Base Sepolia Daily Volume",
            chart_type="bar",
            options={'margin':{'t':100}, 'tickprefix':{'y1': '$'}, 'annotations':True, 'texttemplate':'%{label}<br>%{percent}'}
        )
        cm1.add_title(x=0.5, y=0.9)

    if not blockdag_df.empty:
        cm2.build(
            df=blockdag_df[['amountRequestedUsd']].resample('D').sum(),
            axes_data={'y1':['amountRequestedUsd']},
            title="BlockDAG Testnet Daily Volume",
            chart_type="bar",
            options={'margin':{'t':100}, 'tickprefix':{'y1': '$'}, 'annotations':True, 'texttemplate':'%{label}<br>%{percent}'}
        )
        cm2.add_title(x=0.5, y=0.9)

    graph_json_1 = json.dumps(cm2.return_fig(), cls=PlotlyJSONEncoder) if not blockdag_df.empty else json.dumps({})
    graph_json_2 = json.dumps(cm1.return_fig(), cls=PlotlyJSONEncoder) if not base_df.empty else json.dumps({})

    return graph_json_1, graph_json_2

def init_events_table():
    print('initializing events table')
    conn = sqlite3.connect(data_analysis_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            escrowId TEXT NOT NULL,
            network TEXT NOT NULL,
            payer TEXT NOT NULL,
            createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            amountRequestedTokens INTEGER,
            amountRequestedUsd INTEGER
        )
    """)
    conn.commit()
    conn.close()

def add_event(event):
    try:
        escrowIdBytes = event['args']['escrowId']
        network, _ = find_network_for_settlement(escrowIdBytes)
        args = event['args']

        escrowId = args['escrowId'].hex()
        payer = args['payer']
        amountRequestedTokens = (args['payoutTokensAfterDeskFee'] / 1e6) if 'payoutTokensAfterDeskFee' in args else (args['payoutWeiAfterFee'] / 1e18)
        amountRequestedUsd = (args['postedUsdFromRegistry'] / 1e6) if 'postedUsdFromRegistry' in args else (args['postedUsd'] / 1e6)

        conn = sqlite3.connect(data_analysis_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                escrowId TEXT NOT NULL,
                network TEXT NOT NULL,
                payer TEXT NOT NULL,
                createdAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                amountRequestedTokens INTEGER,
                amountRequestedUsd INTEGER
            )
        """)

        cursor.execute(
            "INSERT INTO events (escrowId, network, payer, amountRequestedTokens, amountRequestedUsd) VALUES (?, ?, ?, ?, ?)",
            (escrowId, network, payer, amountRequestedTokens, amountRequestedUsd)
        )
        conn.commit()
    except Exception as e:
        print(f"[ERROR] Failed to add event: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def events_to_df():
    conn = sqlite3.connect(data_analysis_path)
    try:
        df = pd.read_sql_query("SELECT * FROM events", conn)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        print("No events table found; returning empty DataFrame")
        df = pd.DataFrame(columns=[
            "id", "escrowId", "network", "payer",
            "createdAt", "amountRequestedTokens", "amountRequestedUsd"
        ])
    finally:
        conn.close()
    return df

def make_serializable(obj, preserve_base64_keys=None):
    """
    Recursively make an object JSON-serializable.
    Converts bytes to base64 **only** for selected keys, else hex.
    """
    if preserve_base64_keys is None:
        preserve_base64_keys = {"pdf_bytes"}

    if isinstance(obj, dict):
        return {
            k: (
                base64.b64encode(v).decode("utf-8") if isinstance(v, (bytes, bytearray)) and k in preserve_base64_keys
                else make_serializable(v, preserve_base64_keys)
            )
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [make_serializable(v, preserve_base64_keys) for v in obj]
    elif isinstance(obj, (bytes, bytearray, HexBytes)):
        return obj.hex()
    else:
        return obj
    
def find_network_for_settlement(settlement_id):
    """
    Look for the network and registry type that contains the given settlement_id.
    First checks cache, then falls back to RPC calls if not cached.
    Returns (network, contract) on success, else (None, None).
    """

    # --- Try cache first ---
    try:
        cached = cache.get(settlement_id)
        if cached:
            try:
                entry = json.loads(cached)
                lookup = entry.get("lookup", {})
                net = lookup.get("network")
                address = lookup.get("address")
                if net and address:
                    # print(f"[find_network] Found {settlement_id} in cache → {net}")

                    # Rebuild contract from cached info
                    if net == "blockdag-testnet":
                        w3, account = bdag_w3, bdag_account
                    else:
                        w3, account = base_w3, base_account

                    abi = escrow_bridge_config[net]["abi"]
                    contract = w3.eth.contract(address=address, abi=abi)
                    return net, contract 
            except Exception as e:
                print(f"[find_network] Cache decode error for {settlement_id}: {e}")
    except Exception as e:
        print(f"[find_network] Cache lookup failed for {settlement_id}: {e}")

    # --- Fallback: search on-chain ---
    for net in SUPPORTED_NETWORKS:
        try:
            if net == "blockdag-testnet":
                w3, account = bdag_w3, bdag_account
            else:
                w3, account = base_w3, base_account
        except Exception as e:
            print(f"[find_network] Error connecting to {net}: {e}")
            continue

        address = escrow_bridge_config[net]["address"]
        abi = escrow_bridge_config[net]["abi"]

        try:
            contract = w3.eth.contract(address=address, abi=abi)
        except Exception as e:
            print(f"[find_network] Error loading contract for {net}: {e}")
            continue

        for attempt in range(3):
            try:
                # print(f"[find_network] Checking {net} (attempt {attempt+1})")
                payment = contract.functions.payments(settlement_id).call()

                # if escrow was never initialized, payer will be address(0)
                if payment[0] != "0x0000000000000000000000000000000000000000":
                    # print(f"[✓] Found settlement {settlement_id} on {net}")
                    entry = {
                        "lookup": {
                            "id_hash": settlement_id,
                            "network": net,
                            "address": address,
                        }
                    }
                    cache.set(settlement_id, json.dumps(make_serializable(entry)))
                    return net, contract
                break  # stop retry loop if not found
            except Exception as call_error:
                print(f"[find_network] {net}: {call_error}")
                time.sleep(1)

    return None, None

def get_all_exchange_rates():
    struct = {}
    for network in SUPPORTED_NETWORKS:
        try:
            if network == "blockdag-testnet":
                w3, account = bdag_w3, bdag_account
            else:
                w3, account = base_w3, base_account
        except Exception as e:
            print(f"[find_network] Error connecting to {network}: {e}")

        address = escrow_bridge_config[network]['address']
        abi = escrow_bridge_config[network]['abi']

        try:
            contract = w3.eth.contract(address=address, abi=abi)
        except Exception as e:
            print(f"[find_network] Error loading contract for {network}: {e}")

        if contract:
            rate = get_exchange_rate(contract)

            try:

                usdc_address = contract.functions.usdcToken().call()
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

            struct[network] = {
                "chain_id": w3.eth.chain_id,
                "rate": rate,
                "token": {
                    "address": token_address,
                    "decimals": token_decimals,
                    "symbol": symbol
                }
            }

    return {"exchange_rate": struct}

cached_exchange_rates = {}  # global cache
cached_pending_contract_ids = {}

def update_exchange_rates():
    global cached_exchange_rates
    try:
        cached_exchange_rates = get_all_exchange_rates()
        print("✅ Updated exchange rates:", cached_exchange_rates)
    except Exception as e:
        print("❌ Error updating exchange rates:", e)

def get_pending_contract_ids():
    d = {}
    for net in SUPPORTED_NETWORKS:
        try:
            if net == "blockdag-testnet":
                w3, account = bdag_w3, bdag_account
            else:
                w3, account = base_w3, base_account
        except Exception as e:
            print(f"[find_network] Error connecting to {net}: {e}")
            continue

        contract_address = escrow_bridge_config[net]['address']
        abi = escrow_bridge_config[net]['abi']
        contract = w3.eth.contract(address=contract_address, abi=abi)

        pending = contract.functions.getPendingEscrows().call()

        for escrow_id in pending:
            id_hash = escrow_id.hex()
            d[id_hash] = net

    return d

def update_pending_contract_ids():
    global cached_pending_contract_ids
    try:
        new_cache = get_pending_contract_ids()
        cached_pending_contract_ids = new_cache
        print(f"[cache] Updated pending escrows: {len(cached_pending_contract_ids)} items")
    except Exception as e:
        print(f"[cache] Failed to update pending escrows: {e}")

# Run scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(update_exchange_rates, "interval", minutes=30)  # run every 30 minutes
scheduler.add_job(update_pending_contract_ids, "interval", seconds=30)  # run every minute
scheduler.start()

def handle_init_event(event):
    print(f"[handle_event] New event detected: {event.event}")
    id_hash = event['args']['escrowId'].hex()
    print(f"[handle_event] Detected PaymentInitialized event: {id_hash}")
    pending_ids.add(id_hash)

def handle_settle_event(event):
    print(f"[handle_event] Detected PaymentSettled event: {event['args']['escrowId'].hex()}")
    event_queue.put(event)

async def watch_escrow_status(id_hash: str, webhook_url: str, interval: float = 5.0, max_attempts: int = 120):
    for attempt in range(1, max_attempts + 1):
        status = get_status(id_hash)
        if status.get("status") == "completed":
            async with httpx.AsyncClient() as client:
                await client.post(webhook_url, json={
                    "id_hash": id_hash,
                    "status": status.get("status")
                })
            print(f"✅ Webhook fired for {id_hash}")
            return
        await asyncio.sleep(interval)

    print(f"⚠️ Webhook {id_hash} expired after {max_attempts} attempts")

async def _poll_and_finalize_async(id_hash, max_attempts, delay):
    try:
        print(f"Polling EscrowBridge Smart Contract for {id_hash}")
        id_hash_bytes = Web3.to_bytes(hexstr=id_hash)
        network, bridge = find_network_for_settlement(id_hash_bytes)

        if network == "blockdag-testnet":
            w3, account = bdag_w3, bdag_account
        else:
            w3, account = base_w3, base_account

        for attempt in range(max_attempts):
            is_finalized = bridge.functions.isFinalized(id_hash_bytes).call()
            if is_finalized:
                print(f"Payment is finalized for {id_hash}")
                break
            await asyncio.sleep(delay)
        else:
            print(f"Timeout waiting for finalization for {id_hash}")
            return

        base_tx = bridge.functions.settlePayment(id_hash_bytes).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        })

        try:
            gas_est = w3.eth.estimate_gas(base_tx)
        except Exception as e:
            gas_est = 200000
            print("❌ Error estimating gas:", e)

        latest_block = w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
        priority_fee = w3.to_wei(2, "gwei")
        max_fee = base_fee + priority_fee

        base_tx.update({
            "gas": int(gas_est * 2),
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2
        })

        signed_tx = account.sign_transaction(base_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        if receipt.status == 1:
            print(f"✅ Payment settled: {tx_hash.hex()}")
        else:
            print(f"❌ Transaction failed: {tx_hash.hex()}")

    except Exception as e:
        print(f"Error settling {id_hash}: {e}")
    finally:
        async with asyncio.Lock():
            pending_ids.discard(id_hash)
            active_threads.discard(id_hash)

async def poll_pending_settlements_async(max_attempts=60, delay=5):
    while True:
        for id_hash in list(pending_ids):
            async with asyncio.Lock():
                if id_hash in active_threads:
                    continue
                active_threads.add(id_hash)

            asyncio.create_task(_poll_and_finalize_async(id_hash, max_attempts, delay))

        await asyncio.sleep(2)
 
async def log_loop_for_network(network, lookback=5):
    try:
        if network == "blockdag-testnet":
            w3, account = bdag_w3, bdag_account
        else:
            w3, account = base_w3, base_account
    except Exception as e:
        print(f"[{network}] Error initializing web3/account: {e}")
        return

    try:
        bridge = w3.eth.contract(
            address=escrow_bridge_config[network]["address"],
            abi=escrow_bridge_config[network]["abi"]
        )
    except Exception as e:
        print(f"[{network}] Error initializing contract: {e}")
        return

    last_block = w3.eth.block_number
    print(f"[{network}] Starting event loop from block {last_block}")

    while True:
        try:
            current_block = w3.eth.block_number
            from_block = max(last_block - lookback + 1, 0)  # small lookback to handle reorgs

            if current_block >= from_block:
                logs = bridge.events.PaymentInitialized.get_logs(
                    from_block=from_block,
                    to_block=current_block
                )
                for ev in logs:
                    handle_init_event(ev)

                logs = bridge.events.PaymentSettled.get_logs(
                    from_block=from_block,
                    to_block=current_block
                )
                for ev in logs:
                    handle_settle_event(ev)

                last_block = current_block

            await asyncio.sleep(5)
        except Exception as e:
            print(f"[{network}] Error in log loop: {e}")
            await asyncio.sleep(5)

async def main_log_loop():
    tasks = []
    for network in SUPPORTED_NETWORKS:
        task = asyncio.create_task(log_loop_for_network(network))
        tasks.append(task)
    await asyncio.gather(*tasks)

async def main():
    await asyncio.gather(
        main_log_loop(),
        poll_pending_settlements_async()
    )

def get_status(escrowId: str):
    if escrowId.startswith("0x"):
        escrowId = escrowId[2:]

    print(f"Processing escrowId: {escrowId}")
    
    id_hash_bytes = Web3.to_bytes(hexstr=escrowId)

    network, contract = find_network_for_settlement(id_hash_bytes)

    pending_escrows = contract.functions.getPendingEscrows().call({"from": bdag_account.address})
    completed_escrows = contract.functions.getCompletedEscrows().call({"from": bdag_account.address})

    if id_hash_bytes in pending_escrows:
        return {"status": "pending", "message": "Pending settlement found."}
    elif id_hash_bytes in completed_escrows:
        return {"status": "completed", "message": "Completed settlement found."}
    else:
        return {"error": "Settlement not found."}

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/config")
async def config():
    clean_config = {}
    for net, cfg in escrow_bridge_config.items():
        clean_config[net] = {k:v for k,v in cfg.items() if k != "abi"}
    return clean_config

@app.on_event("startup")
async def startup_event():
    # Schedule your async log loop and polling tasks
    asyncio.create_task(main_log_loop())
    asyncio.create_task(poll_pending_settlements_async())
    asyncio.create_task(poll_and_expire_escrows(interval=60*5))  # every 5 minutes
    update_exchange_rates()
    init_events_table()
    update_pending_contract_ids()

@app.get("/supported_networks")
async def supported_networks():
    struct = {
        "base-sepolia": {
            "chain_id": base_w3.eth.chain_id
        },
        "blockdag-testnet": {
            "chain_id": bdag_w3.eth.chain_id
        }
    }

    return {"supported_networks": struct}

@app.get("/charts")
async def charts():
    graph_json_1, graph_json_2 = create_charts()

    blockdag_free_balance_raw = blockdag_contract.functions.getFreeBalance().call()
    blockdag_free_balance = blockdag_free_balance_raw / 1e18

    base_free_balance_raw = base_contract.functions.getFreeBalance().call()
    base_free_balance = base_free_balance_raw / 1e6

    return {"graph_1": graph_json_1, "graph_2": graph_json_2, "bdag_balance": blockdag_free_balance, "base_usdc_balance": base_free_balance}

@app.get("/")

@app.get("/status/{escrowId}")
async def status(escrowId):
    print(f"Received status request for escrowId: {escrowId}")
    if not escrowId:
        raise HTTPException(status_code=400, detail="No data provided")

    status = get_status(escrowId)

    return {"escrowId": escrowId, "status": status}

@app.get("/events")
async def events():
    df = events_to_df()
    return {"events": df.to_dict(orient="records")}

@app.get("/pending_ids")
async def pending_ids_endpoint():
    return {"pending_ids": cached_pending_contract_ids}

@app.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    if not payload.webhook_url:
        return {"error": "webhook_url required"}
    if not payload.escrowId:
        raise HTTPException(status_code=400, detail="No data provided")

    # Process the webhook payload
    background_tasks.add_task(watch_escrow_status, payload.escrowId, payload.webhook_url)

    return {"escrowId": payload.escrowId, "status": "processed"}

@app.get("/escrow_info/{escrowId}")
async def escrow_info(escrowId):
    print(f"Received escrow_info request for escrowId: {escrowId}")
    if not escrowId:
        raise HTTPException(status_code=400, detail="No data provided")

    escrow_id_bytes = Web3.to_bytes(hexstr=escrowId)

    network, contract = find_network_for_settlement(escrow_id_bytes)

    data = get_payment(escrow_id_bytes, contract)

    data['requestedAmount'] = data.get("requestedAmount") / 1e6 if network == "base-sepolia" else data.get("requestedAmount") / 1e18
    data['requestedAmountUsd'] = data.get("requestedAmountUsd") / 1e6

    data['postedAmount'] = data.get("postedAmount") / 1e6 if network == "base-sepolia" else data.get("postedAmount") / 1e18
    data['postedAmountUsd'] = data.get("postedAmountUsd") / 1e6

    resp = {"escrowId": escrowId, "payment": data}

    return resp

@app.get("/exchange_rates")
def get_exchange_rates():
    return JSONResponse(cached_exchange_rates)

@app.get("/max_escrow_time")
def get_max_escrow_time():
    return {"seconds": max_escrow_time,
            "minutes": max_escrow_time / 60,
            "hours": max_escrow_time / 3600,
            }

@app.get("/fee")
def get_fee():
    return {"fee_pct": fee_pct}

# 4028