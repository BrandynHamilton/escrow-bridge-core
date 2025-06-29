# EscrowBridge Backend

This backend coordinates off-chain settlement monitoring and on-chain payment execution for the EscrowBridge system. It handles event listening, polling, and transaction execution using a Flask server, Web3.py, and ChainSettle SDK.

---

## Components

### 1. Flask App (Listener)

- Listens for smart contract `PaymentInitialized` events
- Polls off-chain oracle via ChainSettle SDK for status
- Calls `settlePayment` onchain once settlement is confirmed
- Provides `POST /status` API for clients to query escrow settlement status

### 2. CLI Utility (Fund Escrow)

- Validates configuration and token info
- Approves USDC to the contract
- Funds EscrowBridge with a specified amount from connected account

### 3. Solidity Contract (EscrowBridge)

- Holds escrowed USDC until settlement is verified
- Supports expiration, payout with fees, and status inspection
- Interfaces with ChainSettle `SettlementRegistry` for attestation and status lookup

---

## Flask Server Endpoints

| Method | Endpoint  | Description                                                                |
| ------ | --------- | -------------------------------------------------------------------------- |
| GET    | `/`       | Health check                                                               |
| POST   | `/status` | Returns status for given escrowId (`pending`, `completed`, or `not found`) |

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

- `ESCROW_BRIDGE_ADDRESS`: Deployed EscrowBridge contract address
- `EVM_PRIVATE_KEY`: Backend wallet key for settlement
- `ALCHEMY_API_KEY`: RPC provider key
- ``

---

## CLI Usage

```bash
python fund_escrow.py --amount 10
```

- Approves & funds EscrowBridge with USDC
- Ensures amount is within contract limits
- Verifies token balance, allowance, and transaction success

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

## Notes

- Ensure the backend wallet has USDC and gas.
- ChainSettle requires off-chain confirmation via PayPal.
- All funds flow through EscrowBridge, not directly to counterparties.
