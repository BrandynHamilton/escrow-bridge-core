import os
import json

SUPPORTED_NETWORKS = ['blockdag-testnet']

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# BlockDAG Testnet Configuration
BLOCKDAG_RPC_URL = os.getenv("BLOCKDAG_RPC_URL", "https://rpc.primordial.bdagscan.com/")
BLOCKDAG_EXPLORER_URL = os.getenv("BLOCKDAG_EXPLORER_URL", "https://primordial.bdagscan.com/tx/")

# Load contract addresses from deployment files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_DIR = os.path.join(BASE_DIR, "..", "..", "contracts", "deployments")

test_usdc_path = os.path.join(CONTRACTS_DIR, "TestUSDC.json")
with open(test_usdc_path, 'r') as f:
    TEST_USDC_ADDRESS = json.load(f)['deployedTo']
