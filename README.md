# EscrowBridge

**EscrowBridge** is a smart contract and listener system that enables trust-minimized, verifiable escrow of payments using off-chain attestations (PayPal) confirmed by the ChainSettle oracle and finalized on-chain.

It allows users to initiate escrowed payments, which are automatically released once ChainSettle confirms the associated off-chain event. The backend monitors for `PaymentInitialized` and `PaymentSettled` events and finalizes payments once confirmed.

## Live Deployment

### Base Sepolia Testnet

| Resource                  | URL/Address                                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Web App**               | [escrowbridge.xyz](https://www.escrowbridge.xyz/)                                                       |
| **Data Dashboard**        | [app.escrowbridge.xyz](https://app.escrowbridge.xyz/)                                                   |
| **EscrowBridge Contract** | `0x30C6E98101C90eD65F4fA5f15188694aCf1D712B`                                                            |
| **Explorer**              | [sepolia.basescan.org](https://sepolia.basescan.org/address/0x30C6E98101C90eD65F4fA5f15188694aCf1D712B) |

---

## Architecture

### Core Components

- **EscrowBridge.sol**: USDC-compatible smart contract that manages escrow lifecycle on Base Sepolia Testnet.
- **TestUSDC.sol**: Test ERC20 token (6 decimals) for testnet USDC simulation (uses native Base Sepolia USDC in production).
- **FastAPI Listener**: Event-driven service that monitors on-chain events, auto-settles payments, expires stale escrows, and exposes REST API endpoints.
- **CLI Tools**: Command line interfaces for users (`escrow-cli`) and administrators (`escrow-admin`).
- **Python SDK**: Sync and async clients for programmatic API access.

### Event Listener

The backend automatically:

- Listens for `PaymentInitialized` events to track new escrows
- Polls the ChainSettle oracle for finalization status
- Calls `settlePayment()` once oracle confirms the off-chain payment
- Expires escrows that exceed `maxEscrowTime`
- Records settled events to SQLite for analytics

---

## Documentation

Comprehensive documentation, guides, and API references are available but not included in this repository.

For support or questions, please open an issue on GitHub.

---

## Running the Listener/API

### Requirements

- [Docker](https://www.docker.com/get-started/)

### 1. Environment Variables

Create a `deploy.env` file in the project root:

```env
EVM_PRIVATE_KEY=<your-private-key>
ACCOUNT_ADDRESS=<your-account-address>
```

### 2. Run the Server

```bash
docker-compose build && docker-compose up
```

### 3. Dashboard

Open http://localhost:4284/ to see the listener dashboard with live analytics.

### 4. API Endpoints

| Endpoint                  | Method | Description                            |
| ------------------------- | ------ | -------------------------------------- |
| `/health`                 | GET    | Health check                           |
| `/config`                 | GET    | Contract configuration                 |
| `/supported_networks`     | GET    | List supported networks                |
| `/exchange_rates`         | GET    | Current exchange rates                 |
| `/fee`                    | GET    | Current fee percentage                 |
| `/max_escrow_time`        | GET    | Max escrow duration                    |
| `/status/{escrowId}`      | GET    | Escrow status (pending/completed)      |
| `/escrow_info/{escrowId}` | GET    | Detailed escrow payment info           |
| `/pending_ids`            | GET    | List pending escrow IDs                |
| `/events`                 | GET    | Settled events history                 |
| `/charts`                 | GET    | Analytics charts data                  |
| `/request_payment`        | POST   | Initiate a new payment request         |
| `/webhook`                | POST   | Register webhook for escrow completion |

Full OpenAPI docs: http://localhost:4284/docs

---

## CLI Tools

### User CLI (`escrow-cli`)

```bash
cd backend
uv run escrow-cli --help
```

**Commands:**

| Command               | Description                                                      |
| --------------------- | ---------------------------------------------------------------- |
| `pay`                 | Full flow: init escrow, register with oracle, poll until settled |
| `init-escrow`         | Initialize escrow on-chain only (no oracle registration)         |
| `register-settlement` | Register escrow data with ChainSettle oracle                     |
| `settle`              | Manually settle an escrow payment                                |
| `poll-status`         | Poll escrow status until completion                              |
| `payment-info`        | Fetch payment details for an escrow ID                           |
| `health`              | Check ChainSettle oracle connectivity                            |
| `config`              | Display contract configuration                                   |

**Example:**

```bash
# Full payment flow (init + register + poll)
uv run escrow-cli pay --amount 10 --network base-sepolia

# Check payment info
uv run escrow-cli payment-info --escrow-id 0x...
```

### Admin CLI (`escrow-admin`)

```bash
cd backend
uv run escrow-admin --help
```

**Commands:**

| Command                | Description                              |
| ---------------------- | ---------------------------------------- |
| `fund-escrow`          | Fund the EscrowBridge contract with USDC |
| `check-exchange-rate`  | Check current exchange rate              |
| `update-exchange-rate` | Update the exchange rate on-chain        |

**Example:**

```bash
# Fund escrow bridge with 1000 USDC
uv run escrow-admin fund-escrow --amount 1000 --network base-sepolia

# Update exchange rate
uv run escrow-admin update-exchange-rate --exchange-rate 1.0 --network base-sepolia
```

---

## Python SDK

### Installation

```bash
pip install httpx
```

### Sync Client

```python
from escrow_bridge.sdk import EscrowBridgeSDK

sdk = EscrowBridgeSDK("https://app.escrowbridge.xyz")

# Check health
print(sdk.health())

# Get exchange rates
rates = sdk.exchange_rates()

# Request a payment
result = sdk.request_payment(
    amount=100.0,
    receiver="0x...",
    email="user@example.com",
    network="base-sepolia"
)
print(f"Escrow ID: {result['id_hash']}")

# Check status
status = sdk.status(result['id_hash'])

# Register webhook for completion notification
sdk.webhook(
    webhook_url="https://yourapp.com/callback",
    escrow_id=result['id_hash']
)
```

### Async Client

```python
from escrow_bridge.sdk import AsyncEscrowBridgeSDK

async with AsyncEscrowBridgeSDK("https://app.escrowbridge.xyz") as sdk:
    health = await sdk.health()
    rates = await sdk.exchange_rates()
    result = await sdk.request_payment(
        amount=50.0,
        receiver="0x...",
        email="user@example.com"
    )
```

---

## Smart Contracts

Built with [Foundry](https://book.getfoundry.sh/).

### Build

```bash
cd contracts
forge build
```

### Test

```bash
forge test
```

### Deploy

```bash
# Deploy TestUSDC
forge script script/DeployTestUSDC.s.sol --rpc-url $RPC_URL --broadcast

# Deploy EscrowBridge
forge script script/Deploy.s.sol --rpc-url $RPC_URL --broadcast
```

---
