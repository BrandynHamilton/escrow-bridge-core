# Escrow Bridge SDK

Python SDK for the Escrow Bridge payment escrow service. Provides both synchronous and asynchronous clients for easy integration.

## Installation

### Using pip

```bash
pip install escrow-bridge-sdk
```

### Using uv

```bash
uv add escrow-bridge-sdk
```

### From source

```bash
# Clone the repository
git clone https://github.com/escrow-bridge/escrow-bridge.git
cd escrow-bridge/packages/python

# Install with pip
pip install -e .

# Or with uv
uv pip install -e .
```

## Quick Start

### Synchronous Usage

```python
from escrow_bridge_sdk import EscrowBridgeSDK

# Initialize the SDK
with EscrowBridgeSDK("http://localhost:8000") as sdk:
    # Check API health
    health = sdk.health()
    print(health)

    # Get exchange rates
    rates = sdk.exchange_rates()
    print(rates)

    # Request a payment
    result = sdk.request_payment(
        amount=100.0,
        receiver="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
        email="user@example.com",
        network="blockdag-testnet"
    )
    print(f"Transaction: {result['tx_hash']}")
    print(f"Escrow ID: {result['id_hash']}")
```

### Asynchronous Usage

```python
import asyncio
from escrow_bridge_sdk import AsyncEscrowBridgeSDK

async def main():
    async with AsyncEscrowBridgeSDK("http://localhost:8000") as sdk:
        # Check API health
        health = await sdk.health()
        print(health)

        # Request a payment
        result = await sdk.request_payment(
            amount=50.0,
            receiver="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            email="user@example.com"
        )
        print(f"Escrow ID: {result['id_hash']}")

asyncio.run(main())
```

## Features

- **Synchronous and Asynchronous Clients**: Choose the client that fits your application architecture
- **Type Hints**: Full type annotations for better IDE support
- **Context Manager Support**: Automatic resource cleanup
- **Comprehensive API Coverage**: Access all Escrow Bridge API endpoints
- **Easy to Use**: Simple and intuitive interface

## API Methods

### Health & Configuration

- `health()` - Check API health status
- `config()` - Get bridge configuration
- `fee()` - Get current fee percentage
- `max_escrow_time()` - Get maximum escrow time allowed

### Escrow Operations

- `request_payment()` - Create a new payment escrow
- `status(escrow_id)` - Get escrow status
- `escrow_info(escrow_id)` - Get detailed escrow information
- `webhook(webhook_url, escrow_id)` - Register webhook for notifications

### Exchange Rates

- `exchange_rates()` - Get current exchange rates for all networks

## Documentation

For complete documentation, see [SDK_DOCUMENTATION.md](../../docs/SDK_DOCUMENTATION.md)

## Requirements

- Python 3.8+
- httpx >= 0.24.0

## Development

### Setup Development Environment

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Or with uv
uv pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Code Formatting

```bash
# Format code
black escrow_bridge_sdk/

# Lint
ruff check escrow_bridge_sdk/

# Type check
mypy escrow_bridge_sdk/
```

## License

MIT License

## Support

For issues and questions:
- GitHub Issues: https://github.com/escrow-bridge/escrow-bridge/issues
- Documentation: See [SDK_DOCUMENTATION.md](../../docs/SDK_DOCUMENTATION.md)
