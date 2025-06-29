# 🌉 EscrowBridge

**EscrowBridge** is a smart contract and listener system that enables trust-minimized, verifiable escrow of payments using off-chain attestations (PayPal) confirmed by the ChainSettle oracle and finalized on-chain.

It allows users to initiate escrowed payments, which are automatically released once ChainSettle confirms the associated off-chain event. The backend monitors for `PaymentInitialized` events and finalizes payments once confirmed.

## Architecture

### Core Components

- **EscrowBridge.sol**: Main smart contract that manages escrow lifecycle.
- **Python Listener**: Flask service that listens for on-chain events, polls ChainSettle, and triggers settlement.
- **Frontend**: Web UI to initiate payments and view statuses.

## Smart Contract

### Key Features

- Trustless USDC escrow with fee support
- Integration with ChainSettle for verified off-chain events
- Automated release via authorized attesters or user
- On-chain and off-chain status tracking

### Contract: `EscrowBridge`

| Function                  | Description                                          |
| ------------------------- | ---------------------------------------------------- |
| `initPayment()`           | Begins a new escrow, reserves USDC in contract       |
| `settlePayment()`         | Settles escrowed payment after ChainSettle confirms  |
| `withdraw()`              | Owner-only withdrawal of free (non-escrowed) USDC    |
| `addAuthorizedAttester()` | Grants settlement rights to backend                  |
| `getFreeBalance()`        | Returns contract balance minus total escrowed amount |

## Workflow

1. **User Initiates Payment** via frontend → calls `initPayment(idHash, emailHash, amount)`
2. **Backend Listener** sees the `PaymentInitialized` event
3. **ChainSettle Oracle** observes off-chain event and calls `postProof(...)` on the registry
4. **Backend Polls Registry** for confirmation via `poll_settlement_status_onchain(...)`
5. **Settlement Triggered** via `settlePayment(idHash)` if confirmed
6. **USDC Released** to user minus protocol fee

### Features

- Listens to `PaymentInitialized` events
- Automatically polls ChainSettle
- Submits `settlePayment` transaction with gas estimation
- Exposes `/status` API for frontend polling

## Frontend

## Demo

[Escrow Bridge MVP Demo](https://drive.google.com/file/d/1_XpgDnOR1mqEqa-00UZo1b7oL_78fjQZ/view?usp=sharing)
