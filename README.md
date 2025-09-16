# 🌉 EscrowBridge

**EscrowBridge** is a smart contract and listener system that enables trust-minimized, verifiable escrow of payments using off-chain attestations (PayPal) confirmed by the ChainSettle oracle and finalized on-chain.

It allows users to initiate escrowed payments, which are automatically released once ChainSettle confirms the associated off-chain event. The backend monitors for `PaymentInitialized` events and finalizes payments once confirmed.

## Architecture

### Core Components

- **EscrowBridge.sol**: ERC20-compatible smart contract that manages escrow lifecycle.
- **EscrowBridgeETH.sol**: Native gas token compatible smart contract that manages escrow lifecycle.
- **Python Listener**: FastAPI service that listens for on-chain events, polls escrow completion, triggers settlement, and exposes API endpoints.
- **CLI**: Command line interface to initiate payments and view statuses.

---

## Documentation

More in-depth documentation can be found at [docs.escrowbridge.xyz](https://docs.escrowbridge.xyz/)

---

## Demos

The `demos` directory has videos showing the workflow for both automated and manual workflows.

---

## Running the Listener/API

### Requirements

- [Docker](https://www.docker.com/get-started/)

### 1. Environment Variables

Create a deploy.env file in the project root with the following variables:

```
EVM_PRIVATE_KEY=
ACCOUNT_ADDRESS=
TENDERLY_API_KEY=

```

### 2. Run the Server

Run this command from the project root

```bash

docker-compose build && docker-compose up

```

### 3. Dashboard

Open http://localhost:4284/ to see the listener dashboard.

### 4. API Endpoints

Open http://localhost:4284/docs to see the available endpoints.

---