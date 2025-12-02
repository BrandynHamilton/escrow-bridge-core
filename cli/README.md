# Escrow Bridge CLI Docker Images

This directory contains Dockerfiles for building and running the Escrow Bridge CLI tools.

## Available Images

### 1. User CLI (`Dockerfile.user`)

The user-facing CLI for initializing payments, settling escrows, and checking status.

**Build:**
```bash
docker build -f Dockerfile.user -t escrow-bridge:user .
```

**Run:**
```bash
# Show help
docker run --rm escrow-bridge:user

# Pay on Base Sepolia (default)
docker run --rm -e PRIVATE_KEY=your_key escrow-bridge:user pay --amount 10

# Initialize escrow
docker run --rm -e PRIVATE_KEY=your_key escrow-bridge:user init_escrow --amount 25

# Settle payment
docker run --rm -e PRIVATE_KEY=your_key escrow-bridge:user settle --escrow-id 0xabcd...

# Check payment info
docker run --rm escrow-bridge:user payment_info --escrow-id 0xabcd...

# Specific network
docker run --rm -e PRIVATE_KEY=your_key escrow-bridge:user pay --amount 10 --network blockdag-testnet
```

**Available Commands:**
- `pay` - Complete payment flow (init → register → settle)
- `init_escrow` - Initialize escrow on-chain only
- `register_settlement` - Register with oracle
- `settle` - Manually settle payment
- `payment_info` - View payment details
- `poll_status` - Monitor escrow status
- `health` - Check oracle health
- `config` - View configuration

### 2. Admin CLI (`Dockerfile.admin`)

The admin CLI for managing the EscrowBridge contract.

**Build:**
```bash
docker build -f Dockerfile.admin -t escrow-bridge:admin .
```

**Run:**
```bash
# Show help
docker run --rm escrow-bridge:admin

# Fund contract
docker run --rm -e PRIVATE_KEY=your_key escrow-bridge:admin fund-escrow --amount 100

# Check exchange rate
docker run --rm escrow-bridge:admin check-exchange-rate

# Update exchange rate
docker run --rm -e PRIVATE_KEY=your_key escrow-bridge:admin update-exchange-rate --exchange-rate 1.0
```

**Available Commands:**
- `fund-escrow` - Fund contract with USDC
- `check-exchange-rate` - Get current exchange rate
- `update-exchange-rate` - Set new exchange rate

## Environment Variables

- `PRIVATE_KEY` - Private key for signing transactions (required for most commands)
- `BLOCKDAG_TESTNET_GATEWAY_URL` - BlockDAG RPC URL (optional, uses default if not set)
- `BASE_SEPOLIA_GATEWAY_URL` - Base Sepolia RPC URL (optional, uses default if not set)
- `CHAINSETTLE_API_URL` - ChainSettle API URL (optional, uses default if not set)

## Networks

Both CLIs support:
- `base-sepolia` (default) - USDC-based escrow on Base Sepolia
- `blockdag-testnet` - USDC-based escrow on BlockDAG Testnet

## Docker Compose Example

```yaml
version: '3.8'

services:
  escrow-cli-user:
    build:
      context: .
      dockerfile: cli/Dockerfile.user
    environment:
      PRIVATE_KEY: ${PRIVATE_KEY}
      BASE_SEPOLIA_GATEWAY_URL: ${BASE_SEPOLIA_GATEWAY_URL}
    command: pay --amount 10

  escrow-cli-admin:
    build:
      context: .
      dockerfile: cli/Dockerfile.admin
    environment:
      PRIVATE_KEY: ${PRIVATE_KEY}
      BASE_SEPOLIA_GATEWAY_URL: ${BASE_SEPOLIA_GATEWAY_URL}
    command: fund-escrow --amount 100
```

## Building from Project Root

```bash
# Build user CLI
docker build -f cli/Dockerfile.user -t escrow-bridge:user .

# Build admin CLI
docker build -f cli/Dockerfile.admin -t escrow-bridge:admin .
```

## Notes

- Both images install the package in editable mode with `pip install -e ./backend`
- The entry points are defined in `backend/pyproject.toml`
- Images inherit from `python:3.10-slim` for minimal size
- Default CMD shows help when no arguments are provided
