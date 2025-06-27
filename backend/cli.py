import click
from chainsettle import network_func, generate_salt, ZERO_ADDRESS, keccak256
from chainsettle_sdk import ChainSettleService
import os
import json
import time

MAX_256 = 2**256 - 1

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

CONFIG_PATH = os.path.join('chainsettle_config.json')
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

ABI_PATH = os.path.join('abi', 'escrowBridgeAbi.json')
with open(ABI_PATH, "r") as f:
    bridge_abi = json.load(f)

@click.command()
@click.option("--amount", default=1, type=int, help="Amount of USDC to top up the EscrowBridge contract with (normalized).")
def main(amount):
    network = 'base'
    PRIVATE_KEY = os.getenv('EVM_PRIVATE_KEY')
    ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
    ESCROW_BRIDGE_ADDRESS = os.getenv('ESCROW_BRIDGE_ADDRESS')
    REGISTRY_ADDRESS = config[network]['registry_addresses']['SettlementRegistry']
    w3, account = network_func(
        network=network,
        ALCHEMY_API_KEY=ALCHEMY_API_KEY,
        PRIVATE_KEY=PRIVATE_KEY
    )

    bridge = w3.eth.contract(address=ESCROW_BRIDGE_ADDRESS, abi=bridge_abi)
    print(f"Using EOA = {account.address}")

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
    usdc_address = bridge.functions.usdcToken().call()
    print(f"> EscrowBridge.usdcToken() = {usdc_address}")

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
    
    amount_raw = int(amount * (10 ** token_decimals))  # Convert to raw units
    top_up = amount_raw
    print(f"→ Ramp contract needs an additional {top_up} raw USDC units "
            f"(≈ {top_up / (10**token_decimals):.6f} USDC).")

    # 10.a) Check our EOA’s own USDC balance
    owner_raw_balance = erc20.functions.balanceOf(account.address).call()
    owner_human_balance = owner_raw_balance / (10 ** token_decimals)
    print(f"> EOA USDC balance (raw) = {owner_raw_balance}  → (≈{owner_human_balance:.6f} USDC)")

    if owner_raw_balance < top_up:
        raise Exception(
            f"❌ EOA’s USDC ({owner_human_balance:.6f} USDC) is less than required "
            f"{top_up / (10**token_decimals):.6f} USDC."
        )

    # 10.b) Build + send ERC20.approve(SettlementRamp, top_up)
    #      Fetch nonce once:
    base_nonce = w3.eth.get_transaction_count(account.address)
    approve_tx = erc20.functions.approve(ESCROW_BRIDGE_ADDRESS, MAX_256).build_transaction({
        "from": account.address,
        "nonce": base_nonce,
    })
    gas_est = w3.eth.estimate_gas(approve_tx)
    latest_block = w3.eth.get_block("latest")
    base_fee = latest_block.get("baseFeePerGas", w3.to_wei(15, "gwei"))
    priority_fee = w3.to_wei(2, "gwei")
    max_fee = base_fee + priority_fee

    approve_tx.update({
        "gas": int(gas_est * 1.2),
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": max_fee,
        "type": 2
    })
    signed_approve = account.sign_transaction(approve_tx)
    h_approve = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    receipt_approve = w3.eth.wait_for_transaction_receipt(h_approve)
    if receipt_approve.status != 1:
        raise Exception("❌ ERC20.approve(...) reverted")

    print(f"✓ Approved {top_up} raw USDC to EscrowBridge (tx: {h_approve.hex()})")

    time.sleep(10)  # Wait for the approval to be mined

    # 10.c) Double-check allowance
    current_allowance = erc20.functions.allowance(account.address, ESCROW_BRIDGE_ADDRESS).call()
    print(f"🔍 Post-approve: allowance = {current_allowance} (need ≥ {top_up})")
    if current_allowance < top_up:
        raise Exception("❌ Allowance was not set correctly.")

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
        "gas": int(gas_est * 1.2),
        "maxPriorityFeePerGas": priority_fee,
        "maxFeePerGas": max_fee,
        "type": 2
    })
    signed_fund = account.sign_transaction(fund_tx)
    h_fund = w3.eth.send_raw_transaction(signed_fund.raw_transaction)
    receipt_fund = w3.eth.wait_for_transaction_receipt(h_fund)
    if receipt_fund.status != 1:
        raise Exception("❌ EscrowBridge.fundEscrow(...) reverted")

    print(f"✓ Funded EscrowBridge with {top_up} raw USDC "
            f"(≈ {top_up / (10**token_decimals):.6f} USDC)  Tx: {h_fund.hex()}")
    
    time.sleep(10)
    
    # 10.e) Double-check the EscrowBridge contract’s USDC balance
    bridge_raw_balance = erc20.functions.balanceOf(ESCROW_BRIDGE_ADDRESS).call()
    bridge_human_balance = bridge_raw_balance / (10 ** token_decimals)      
    print(f"🔍 Post-fund: EscrowBridge USDC balance (raw) = {bridge_raw_balance} "
          f"→ (≈ {bridge_human_balance:.6f} USDC)")
    
if __name__ == "__main__":
    main()
