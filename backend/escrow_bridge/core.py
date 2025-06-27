import os
from web3 import Web3   
from dotenv import load_dotenv
load_dotenv()

def network_func(PRIVATE_KEY, network='ethereum',ALCHEMY_API_KEY=None):
    if network not in ['ethereum', 'base', 'blockdag']:
        raise Exception(f"Network {network} not supported. Supported networks are: {['ethereum', 'base', 'blockdag']}")
    
    # Compose Gateway URLs
    if network == 'ethereum':
        if ALCHEMY_API_KEY is None:
            GATEWAY = 'https://eth-sepolia.public.blastapi.io'
        else:
            try:
                GATEWAY = f"https://eth-sepolia.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
            except Exception as e:
                print(f"Failed to connect to Alchemy (Ethereum): {e}")
                GATEWAY = 'https://eth-sepolia.public.blastapi.io'

    elif network == 'base':
        if ALCHEMY_API_KEY is None:
            GATEWAY = 'https://base-sepolia.public.blastapi.io'
        else:
            try:
                GATEWAY = f"https://base-sepolia.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
            except Exception as e:
                print(f"Failed to connect to Alchemy (Base): {e}")
                GATEWAY = 'https://base-sepolia.public.blastapi.io'

    elif network == 'blockdag':
        GATEWAY = 'https://rpc.primordial.bdagscan.com/'

    w3 = Web3(Web3.HTTPProvider(GATEWAY))

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
