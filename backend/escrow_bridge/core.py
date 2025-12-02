import os
from web3 import Web3
from dotenv import load_dotenv
from escrow_bridge.config import BLOCKDAG_RPC_URL
load_dotenv()

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

def network_func(network='blockdag-testnet'):

    ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
    TENDERLY_API_KEY = os.getenv('TENDERLY_API_KEY')
    PRIVATE_KEY = os.getenv('EVM_PRIVATE_KEY')

    # Compose Gateway URLs
    if network == 'ethereum-sepolia':
        if ALCHEMY_API_KEY is None:
            GATEWAY = 'https://eth-sepolia.public.blastapi.io'
        else:
            try:
                GATEWAY = f"https://eth-sepolia.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
            except Exception as e:
                print(f"Failed to connect to Alchemy (Ethereum): {e}")
                GATEWAY = 'https://eth-sepolia.public.blastapi.io'

    elif network == 'base-sepolia':
        
        GATEWAY = f'https://base-sepolia.g.alchemy.com/v2/{ALCHEMY_API_KEY}'

    elif network == 'blockdag-testnet':
        GATEWAY = BLOCKDAG_RPC_URL

    w3 = Web3(Web3.HTTPProvider(GATEWAY))

    print(f"Connecting to {network} at {GATEWAY}...")

    account = None

    if w3.is_connected():
        try:
            account = w3.eth.account.from_key(PRIVATE_KEY)
            try:
                latest_block = w3.eth.get_block('latest')['number']
            except:
                latest_block = None
            print(f"Connected to {network} with account {account} - Block {latest_block}")
            return w3, account
        except Exception as e:
            print(f"Connected but failed to fetch block. Error: {e}")
            return w3, account
    else:
        print(f"Failed to connect to {network}")

def generate_salt():
    """
    Generates a random salt value for settlement registration.
    This is used to create a unique identifier for the settlement.
    """
    return os.urandom(32).hex()  # 16 bytes = 32 hex characters

def get_exchange_rate(contract) -> float:
    """
    Fetches the current exchange rate from the smart contract.
    """
    try:
        rate = contract.functions.getExchangeRate().call()
        return rate / 1e6  # Convert from USD(6) to float
    except Exception as e:
        print(f"Error fetching exchange rate: {e}")
        return 0.0
    
def get_payment(escrow_id: bytes, bridge):
    """
    Calls EscrowBridge.payments(escrowId) and returns the Payment struct as a dict.
    
    :param escrow_id: bytes32 escrowId (hex string, e.g. '0xabc123...')
    :return: dict with Payment data
    """
    try:
        p = bridge.functions.payments(escrow_id).call()
        is_settled = bridge.functions.isSettled(escrow_id).call()

        return {
            "payer": p[0],
            "recipient": p[1],
            "requestedAmount": p[2],
            "requestedAmountUsd": p[3],
            "postedAmount": p[4],
            "postedAmountUsd": p[5],
            "lastCheckTimestamp": p[6],
            "checkCount": p[7],
            "createdAt": p[8],
            "isSettled": is_settled
        }

    except Exception as e:
        print(f"Error fetching payment: {e}")
        return None
    
def get_decimals(w3, contract):
    try:
        usdc_address = contract.functions.usdcToken().call()
        erc20 = w3.eth.contract(address=usdc_address, abi=erc20_abi)

        # 4) Query the token’s decimals() (USDC is normally 6, but let’s be safe)
        token_decimals = erc20.functions.decimals().call()
    except Exception as e:
        print("❌ Error fetching token details:", e)
        token_decimals = 18
    return token_decimals