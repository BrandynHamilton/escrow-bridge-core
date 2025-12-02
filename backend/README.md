# EscrowBridge Backend

This backend coordinates off-chain settlement monitoring and on-chain payment execution for the EscrowBridge system. It handles event listening, polling, and transaction execution using a FastAPI server, Web3.py, and ChainSettle SDK.

Supported networks:
- **Base Sepolia** (default) - USDC-based escrow
- **BlockDAG Testnet** - USDC-based escrow

---

## Components

### 1. FastAPI Server (Listener)

- Listens for smart contract `PaymentInitialized` events
- Polls off-chain oracle via ChainSettle SDK for status
- Calls `settlePayment` onchain once settlement is confirmed
- Provides REST API for clients to query escrow settlement status
- Auto-expires stale escrows

### 2. User CLI (`escrow-bridge`)

- Complete payment flow: initialize escrow → register with oracle → poll for settlement
- Initialize escrow on-chain only (skip oracle registration)
- Settle payments manually
- Check payment info and escrow status
- Validate oracle health

### 3. Admin CLI (`escrow-bridge-admin`)

- Fund EscrowBridge contract with USDC
- Check and update exchange rates
- Manage contract parameters

### 4. Solidity Contract (EscrowBridge)

- Holds escrowed USDC until settlement is verified
- Supports expiration, payout with fees, and status inspection
- Interfaces with ChainSettle `SettlementRegistry` for attestation and status lookup

---

## FastAPI Server Endpoints

| Method | Endpoint                    | Description                                                                |
| ------ | --------------------------- | -------------------------------------------------------------------------- |
| GET    | `/`                         | Home page                                                                  |
| GET    | `/health`                   | Health check                                                               |
| GET    | `/config`                   | Contract configuration                                                     |
| GET    | `/supported_networks`       | List of supported networks and chain IDs                                   |
| GET    | `/status/{escrowId}`        | Returns status for given escrowId (`pending`, `completed`, or `not found`) |
| GET    | `/escrow_info/{escrowId}`   | Get detailed payment info for an escrow                                    |
| GET    | `/events`                   | Get all settled events                                                     |
| GET    | `/charts`                   | Get settlement volume charts                                               |
| GET    | `/exchange_rates`           | Get current exchange rates for all networks                                |
| GET    | `/max_escrow_time`          | Get max escrow timeout in seconds/minutes/hours                            |
| GET    | `/fee`                      | Get current fee percentage                                                 |
| GET    | `/pending_ids`              | Get list of pending escrow IDs                                             |
| POST   | `/webhook`                  | Register webhook for escrow completion                                    |
| POST   | `/request_payment`          | Request a payment (initialize escrow)                                      |

---

## Main Concepts

### Escrow Flow

1. `initPayment` is called on-chain → emits `PaymentInitialized`
2. Backend detects event and polls ChainSettle
3. When off-chain status = `Confirmed`, backend finalizes via `settlePayment`

### Security Features

- `nonReentrant` modifiers
- Fee accounting with `feeRecipient`
- Timeout-based expiration if settlement fails

---

## Environment Variables (.env)

- `PRIVATE_KEY`: Private key for signing transactions
- `EVM_PRIVATE_KEY`: Backend wallet key for settlement (listener)
- `BLOCKDAG_TESTNET_GATEWAY_URL`: BlockDAG RPC URL (optional)
- `BASE_SEPOLIA_GATEWAY_URL`: Base Sepolia RPC URL (optional)
- `CHAINSETTLE_API_URL`: ChainSettle API URL for off-chain settlement

---

## Installation

Install the package in development mode to enable CLI commands:

```bash
cd backend
uv pip install -e .
```

Or with pip:

```bash
pip install -e .
```

---

## CLI Usage

### User Commands (`escrow-bridge`)

**Complete Payment Flow** - Initialize → Register with oracle → Poll for settlement:
```bash
escrow-bridge pay --amount 10 [--network base-sepolia]
```

**Initialize Escrow Only** - On-chain only, no oracle registration:
```bash
escrow-bridge init_escrow --amount 10 [--network base-sepolia]
```

**Register Escrow with Oracle** - Register previously initialized escrow:
```bash
escrow-bridge register_settlement
```

**Settle Payment** - Manually settle an escrow:
```bash
escrow-bridge settle [--escrow-id <id>]
```

**Check Payment Info** - View escrow details:
```bash
escrow-bridge payment_info [--escrow-id <id>]
```

**Poll Escrow Status** - Monitor settlement progress:
```bash
escrow-bridge poll_status [--escrow-id <id>] [--timeout 300] [--delay 10]
```

**Check Oracle Health** - Verify ChainSettle API is reachable:
```bash
escrow-bridge health
```

**View Configuration** - Display contract addresses and networks:
```bash
escrow-bridge config
```

### Admin Commands (`escrow-bridge-admin`)

**Fund Escrow Bridge** - Approve and fund USDC:
```bash
escrow-bridge-admin fund-escrow --amount 10 [--network base-sepolia]
```

**Check Exchange Rate** - Get current USD exchange rate:
```bash
escrow-bridge-admin check-exchange-rate [--network base-sepolia]
```

**Update Exchange Rate** - Set new exchange rate:
```bash
escrow-bridge-admin update-exchange-rate --exchange-rate 1.0 [--network base-sepolia]
```

### Common Options

- `--network` - Target network: `base-sepolia` (default) or `blockdag-testnet`
- `--private-key` - Private key (or use `PRIVATE_KEY` env var)
- `--force` - Bypass safety checks (use with caution)
- `--help` - Show command help

### Examples

```bash
# Fund contract on Base Sepolia with 100 USDC
escrow-bridge-admin fund-escrow --amount 100

# Pay 50 USDC on BlockDAG
escrow-bridge pay --amount 50 --network blockdag-testnet

# Initialize escrow without oracle registration
escrow-bridge init_escrow --amount 25 --recipient 0x1234...

# Settle an escrow
escrow-bridge settle --escrow-id 0xabcd...
```

---

## Contract Summary: `EscrowBridge.sol`

- `initPayment(...)` — Initializes a settlement
- `settlePayment(...)` — Finalizes after confirmation
- `fundEscrow(...)` — Owner can deposit USDC
- `expireEscrow(...)` — Marks escrow expired after timeout
- `getUsdcBalance()`, `getFreeBalance()` — Balance utilities

Events:

- `PaymentInitialized`
- `PaymentSettled`
- `EscrowExpired`

---

## Escrow Expiration: `maxEscrowTime`

- `maxEscrowTime` is a contract parameter (in seconds) that sets the maximum time a settlement can remain pending.
- If a settlement is not confirmed within this window, the escrow is **expired**, and the funds are released without settlement.
- This protects liquidity and ensures stale or failed off-chain attestations do not lock up capital indefinitely.
- The backend auto-checks expiration before calling `settlePayment()`.

"""

## Integrations

- ChainSettle SDK for polling settlement confirmations
- MetaMask/ethers.js frontend submits initial `initPayment`

---

## Dependencies

- `web3`
- `flask`
- `python-dotenv`
- `click`
- `chainsettle-sdk`

---

## Running the Server

Start the FastAPI listener:

```bash
uv run python main.py
```

The server will:
- Connect to the configured network (Base Sepolia or BlockDAG)
- Listen for PaymentInitialized events
- Automatically poll and settle confirmed escrows
- Expire stale escrows after maxEscrowTime

## Notes

- Ensure the backend wallet has sufficient gas (ETH or native token) for transactions
- Ensure the backend wallet has USDC for funding when using `fund-escrow`
- ChainSettle requires off-chain confirmation via PayPal
- All funds flow through EscrowBridge, not directly to counterparties
- Use `--network blockdag-testnet` flag to use BlockDAG instead of the default Base Sepolia
- CLI commands cache the last escrow ID, salt, and settlement ID for convenience
- Each network has its own contract instance - make sure you're using the right one
