# 🌉 Escrow Bridge

**Escrow Bridge** is a smart contract and listener system that enables trust-minimized, verifiable escrow of payments using off-chain attestations (PayPal) confirmed by a web3 oracle and finalized on-chain.

It allows users to initiate escrowed payments, which are automatically released once the oracle confirms the associated off-chain event. The backend monitors for `PaymentInitialized` events and finalizes payments once confirmed.

## Architecture

### Core Components

- **EscrowBridge.sol**: Main smart contract that manages escrow lifecycle.
- **Python Listener**: Lightweight service that listens for on-chain events, polls web3 oracle, and triggers settlement.
- **Command-Line Interface**: CLI to initiate payments and poll for completion.

## Smart Contract

### Key Features

- Trust-minimized USDC escrow with fee support
- Integration with a web3 oracle for verified off-chain events
- Automated release via authorized agents or manually via user
- On-chain status tracking

### Contract: `EscrowBridge`

| Function                  | Description                                          |
| ------------------------- | ---------------------------------------------------- |
| `initPayment()`           | Begins a new escrow, reserves USDC in contract       |
| `settlePayment()`         | Settles escrowed payment after oracle confirms       |
| `withdraw()`              | Owner-only withdrawal of free (non-escrowed) USDC    |
| `addAuthorizedAttester()` | Grants settlement rights to backend                  |
| `getFreeBalance()`        | Returns contract balance minus total escrowed amount |

## Workflow

1. **User Initiates Payment** via cli → calls `initPayment(idHash, emailHash, amount)`
2. **Backend Listener** sees the `PaymentInitialized` event
3. **Web3 Oracle** observes off-chain event and updates its Settlement Registry
4. **Settlement Triggered** via `settlePayment(idHash)` if confirmed
5. **USDC Released** to user minus protocol and payment processor (PayPal) fees

### Features

- Listens to `PaymentInitialized` events
- Automatically polls smart contract oracle for status
- Submits `settlePayment` transaction with gas estimation

## Deployments

EscrowBridge
| Network | Address |
|--------------------|----------------------------------------------|
| Base Sepolia | [0xe2241a04c7347FD6571979b1F4a41C267fcf1A15](https://sepolia.basescan.org/address/0xe2241a04c7347FD6571979b1F4a41C267fcf1A15) |

## CLI & Listener

### Features

The `cli.py` script allows you to interact with the EscrowBridge contract directly from the command line. It enables you to:

- Request a USDC escrow transaction
- Automatically validate min/max constraints
- Confirm contract liquidity
- Generate and hash a unique settlement ID
- Submit the `initPayment(...)` transaction on-chain
- Store off-chain metadata (email, salt, recipient)
- Poll on-chain for settlement status

The `backend/main.py` script is a listener script which acts on `initPayment` events emitted by the EscrowBridge smart contract, and calls `settlePayment` onchain once the PayPal payment is confirmed by the web3 oracle.

#### PayPal Credentials

The web3 oracle solution will send an email to the specified email address with a link to complete a PayPal sandbox payment at this base url: `http://provider.boogle.cloud:31151/`.

**The following test credentials should be used:**

- email: sb-w7oqu40942591@personal.example.com
- password: 1eh)\_t_N

### How to Use

#### Prerequisites

- Python 3.8+
- pip or [`uv`](https://github.com/astral-sh/uv)
- Internet access
- [Alchemy RPC API Key](https://www.alchemy.com/)
- EVM account private key with enough [Base Sepolia ETH](https://docs.base.org/base-chain/tools/network-faucets) for transaction fees

#### Step 1: Install Dependencies

Install the backend package:

```bash
pip install uv # Only if not already installed
uv pip install ./backend
```

#### Step 2: Prepare `.env`

Copy the .env.sample file to a .env file by running this command (depending on CLI/OS):

```bash
# Unix/macOS/Linux
cp .env.sample .env

# Windows Command Prompt
copy .env.sample .env

# Windows PowerShell
Copy-Item .env.sample .env
```

**Make sure to fill the `.env` file with an EVM account private key:**

```env
PRIVATE_KEY=your_private_key
ALCHEMY_API_KEY=your_alchemy_api_key
```

#### Step 3: Run the Listener

```bash
cd backend
uv run python main.py
```

#### Step 4: Run the CLI

```bash
uv run python cli.py --amount <amount> --recipient-address <wallet_address> --email <user_email>
```

If `--recipient-address` is left empty, it defaults to the msg.sender (connected EVM account)

##### Example:

```bash
uv run python cli.py --amount 10 --recipient-address 0xabc123... --email user@example.com
```

This will:

1. Load contract configuration
2. Verify your USDC request is within bounds
3. Check EscrowBridge liquidity
4. Generate a random settlement ID + salt
5. Compute ID hash and email hash
6. Call `initPayment(...)` on-chain
7. Poll for confirmation until the escrow completes
