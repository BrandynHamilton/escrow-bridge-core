
import webbrowser
from escrow_bridge import network_func, generate_salt, ZERO_ADDRESS
import os
from typing import Dict, Optional, List
from web3 import Web3
import secrets

from dotenv import load_dotenv
import time
import json
import requests

load_dotenv()

BACKEND_URL = "http://localhost:4284"  
WEBHOOK_URL = "http://localhost:9200/my-webhook"

THIRD_PARTY_KEY = os.getenv("THIRD_PARTY_KEY")
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')

network = "base"

erc20_abi = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
native_bridge_artifact_path = os.path.join(BASE_DIR, "..", "..", "contracts", "out", "EscrowBridgeETH.sol", "EscrowBridgeETH.json")
token_bridge_artifact_path = os.path.join(BASE_DIR, "..", "..", "contracts", "out", "EscrowBridge.sol", "EscrowBridge.json")

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
BASE_SEPOLIA_GATEWAY_URL = os.getenv('BASE_SEPOLIA_GATEWAY_URL', 'https://sepolia.base.org/')
BLOCKDAG_TESTNET_GATEWAY_URL = os.getenv('BLOCKDAG_TESTNET_GATEWAY_URL', 'https://rpc.primordial.bdagscan.com/')

with open(native_bridge_artifact_path, 'r') as f:
    native_bridge_abi = json.load(f)['abi']

with open(token_bridge_artifact_path, 'r') as f:
    token_bridge_abi = json.load(f)['abi']

escrow_bridge_config = {
    "base-sepolia": {
        "address": os.getenv('TOKEN_ESCROW_BRIDGE_ADDRESS_BASE', '0xa8e105eBfd87382a80B9Cc09Aa5c670Ca8609490'),
        "abi": token_bridge_abi,
    },
    "blockdag-testnet": {
        "address": os.getenv('NATIVE_ESCROW_BRIDGE_ADDRESS_BDAG', '0xFBde820bca4Ee8c024583339F8F55aA527970ef7'),
        "abi": native_bridge_abi
    },
}

def main(network, amount):
    GATEWAY = BLOCKDAG_TESTNET_GATEWAY_URL if network == "blockdag-testnet" else BASE_SEPOLIA_GATEWAY_URL
    EXPL_URL = "https://sepolia-explorer.base.org/tx/" if network == "base-sepolia" else "https://primordial.bdagscan.com/tx/"
    w3 = Web3(Web3.HTTPProvider(GATEWAY))
    account = w3.eth.account.from_key(PRIVATE_KEY)

    recipient = account.address

    contract_address = escrow_bridge_config[network]['address']
    bridge_abi = escrow_bridge_config[network]['abi']

    bridge = w3.eth.contract(address=contract_address, abi=bridge_abi)
    print(f"Using EOA = {account.address}")
    print(f"Recipient = {recipient}")
    print(f"Using EscrowBridge contract = {contract_address}")

    recipient_email = bridge.functions.recipientEmail().call()
    print(f"> EscrowBridge.recipientEmail() = {recipient_email}")

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

    fee = bridge.functions.fee().call()
    print(f"> EscrowBridge.fee() = {fee / 10000} ")

    min_human = min_raw / (10 ** token_decimals)
    max_human = max_raw / (10 ** token_decimals)
    print(f"  → in human USDC: min = {min_human:.6f}, max = {max_human:.6f} ")

    # 6) Validate the user‐supplied “amount”
    if amount < min_human or amount > max_human:
        raise ValueError(
            f"❌ Requested amount {amount} USDC is out of bounds: "
            f"minimum = {min_human:.6f} USDC, maximum = {max_human:.6f} USDC"
        )

    amount_raw = int(amount * (10 ** token_decimals))  # Convert to raw units

    bridge_raw_balance = erc20.functions.balanceOf(contract_address).call() if erc20 else w3.eth.get_balance(contract_address)
    bridge_human_balance = bridge_raw_balance / (10 ** token_decimals)  

    ramp_usdc_balance = bridge.functions.getFreeBalance().call()
    human_ramp_balance = ramp_usdc_balance / (10 ** token_decimals)
    print(f"> SettlementRamp USDC balance (raw) = {ramp_usdc_balance}")
    print(f"  → in human USDC = {human_ramp_balance:.6f} USDC")

    print(f"> EscrowBridge USDC balance (raw) = {bridge_raw_balance}  → (≈{bridge_human_balance:.6f} USDC)")
    print(f" EscrowBridge free balance: (≈{human_ramp_balance:.6f} USDC)")

    if amount > human_ramp_balance:
        raise ValueError(
            f"❌ Requested amount {amount} USDC exceeds available funds "
            f"(≈{human_ramp_balance:.6f} USDC)"
        )

    salt = generate_salt()
    print(f"> Generated salt = {salt}")
    if not salt.startswith("0x"):
        salt = "0x" + salt

    salt_bytes = Web3.to_bytes(hexstr=salt)

    settlement_id = secrets.token_hex(18)

    # if not settlement_id.startswith("0x"):
    #     settlement_id = "0x" + settlement_id

    print(f"> Generated settlement_id = {settlement_id}")
    print(f"salt_bytes = {salt_bytes}")

    id_hash_bytes = w3.solidity_keccak(
        ["bytes32", "string"],
        [salt_bytes, settlement_id]
    )

    id_hash = id_hash_bytes.hex()
    print(f"> Computed id_hash = {id_hash}")

    base_tx = bridge.functions.initPayment(
        id_hash_bytes,
        amount_raw,
        recipient
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, 'pending'),
    })
    gas_est = w3.eth.estimate_gas(base_tx)
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
    signed_init = account.sign_transaction(base_tx)
    h_init = w3.eth.send_raw_transaction(signed_init.raw_transaction)
    receipt_init = w3.eth.wait_for_transaction_receipt(h_init)
    if receipt_init.status != 1:
        raise Exception("❌ SettlementRamp.initPayment(...) reverted")

    print(f"✓ initPayment({settlement_id}, {amount:.6f} USDC) submitted → Tx: {h_init.hex()}")
    print(f"→ View on Explorer: {EXPL_URL}{'0x' + h_init.hex()}")

    totalEscrowed = bridge.functions.totalEscrowed().call()
    print(f"EscrowBridge.totalEscrowed() = {totalEscrowed} raw USDC ")

    payload = {
        "salt": salt,
        "settlement_id": settlement_id,
        "recipient_email": recipient_email,
    }
    headers = {"content-type": "application/json"}
    print(f'payload: {payload}')
    r = requests.post(f"{os.getenv('CHAINSETTLE_API_URL')}/settlement/register_settlement", 
                        json=payload, headers=headers)
    r.raise_for_status()
    resp = r.json()
    if 'user_url' in resp.get('settlement_info', {}):
        print(f"✓ User URL: {resp['settlement_info']['user_url']}")
        webbrowser.open(resp['settlement_info']['user_url'])
    else:
        print("⚠️ User URL not found in response.")

    # Step 2: subscribe webhook
    resp = requests.post(
        f"{BACKEND_URL}/webhook/",
        json={"webhook_url": WEBHOOK_URL,
              "escrowId": id_hash}
    )
    print("🔗 Subscribed:", resp.json())

if __name__ == "__main__":
    main(
        'base-sepolia',
        1
    )