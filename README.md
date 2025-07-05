# 🌉 EscrowBridge

**EscrowBridge** is a smart contract and listener system that enables trust-minimized, verifiable escrow of payments using off-chain attestations (PayPal) confirmed by a web3 oracle and finalized on-chain.

It allows users to initiate escrowed payments, which are automatically released once the oracle confirms the associated off-chain event. The backend monitors for `PaymentInitialized` events and finalizes payments once confirmed.

## Architecture

### Core Components

- **EscrowBridge.sol**: Main smart contract that manages escrow lifecycle.
- **Python Listener**: Lightweight service that listens for on-chain events, polls web3 oracle, and triggers settlement.
- **Frontend**: Web UI to initiate payments and view statuses.

## Smart Contract

### Key Features

- Trustless USDC escrow with fee support
- Integration with a web3 oracle for verified off-chain events
- Automated release via authorized attesters or user
- On-chain and off-chain status tracking

### Contract: `EscrowBridge`

| Function                  | Description                                          |
| ------------------------- | ---------------------------------------------------- |
| `initPayment()`           | Begins a new escrow, reserves USDC in contract       |
| `settlePayment()`         | Settles escrowed payment after oracle confirms       |
| `withdraw()`              | Owner-only withdrawal of free (non-escrowed) USDC    |
| `addAuthorizedAttester()` | Grants settlement rights to backend                  |
| `getFreeBalance()`        | Returns contract balance minus total escrowed amount |

## Workflow

1. **User Initiates Payment** via frontend → calls `initPayment(idHash, emailHash, amount)`
2. **Backend Listener** sees the `PaymentInitialized` event
3. **Web3 Oracle** observes off-chain event and calls `postProof(...)` on the registry
4. **Backend Polls Registry** for confirmation via `poll_settlement_status_onchain(...)`
5. **Settlement Triggered** via `settlePayment(idHash)` if confirmed
6. **USDC Released** to user minus protocol fee

### Features

- Listens to `PaymentInitialized` events
- Automatically polls web3 oracle
- Submits `settlePayment` transaction with gas estimation

## CLI

### Features

The `cli.py` script allows you to interact with the EscrowBridge contract directly from the command line. It enables you to:

- Request a USDC escrow transaction
- Automatically validate min/max constraints
- Confirm contract liquidity
- Generate and hash a unique settlement ID
- Submit the `initPayment(...)` transaction on-chain
- Store off-chain metadata (email, salt, recipient)
- Poll on-chain for settlement status

### How to Use

#### Step 1: Install Dependencies

Use [`uv`](https://github.com/astral-sh/uv) to install the backend package:

```bash
uv pip install ./backend
```

#### Step 2: Prepare `.env`

Make sure your `.env` includes the following keys:

```env
EVM_PRIVATE_KEY=your_private_key
ESCROW_BRIDGE_ADDRESS=0xYourEscrowBridgeAddress
GATEWAY=https://base-sepolia.public.blastapi.io
```

#### Step 3: Run the CLI

```bash
python cli.py --amount <amount> --recipient <wallet_address> --email <user_email>
```

##### Example:

```bash
python cli.py --amount 500 --recipient 0xabc123... --email user@example.com
```

This will:

1. Load contract configuration
2. Verify your USDC request is within bounds
3. Check EscrowBridge liquidity
4. Generate a random settlement ID + salt
5. Compute ID hash and email hash
6. Call `initPayment(...)` on-chain
7. POST the salt and metadata to your backend
8. Poll for confirmation until the escrow completes
