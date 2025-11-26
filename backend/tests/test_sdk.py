"""
Test script for the Escrow Bridge SDK.

Run with:
    python tests/test_sdk.py

Make sure the API server is running before executing this script.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from escrow_bridge.sdk import EscrowBridgeSDK, AsyncEscrowBridgeSDK
import asyncio

# Configuration
BASE_URL = os.getenv("ESCROW_API_URL", "http://localhost:4284")

# Test data - update these for your environment
TEST_ESCROW_ID = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
TEST_RECEIVER = "0x742d35Cc6634C0532925a3b844Bc9e7595f5bB01"  # Example address
TEST_EMAIL = "test@example.com"
TEST_WEBHOOK_URL = "https://webhook.site/test"


def test_sync_sdk():
    """Test all synchronous SDK methods."""
    print("=" * 60)
    print("Testing Synchronous EscrowBridgeSDK")
    print("=" * 60)

    sdk = EscrowBridgeSDK(BASE_URL)

    # Test health
    print("\n[1] Testing health()...")
    try:
        result = sdk.health()
        print(f"    Result: {result}")
        assert result.get("status") == "ok", "Health check failed"
        print("    PASSED")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test config
    print("\n[2] Testing config()...")
    try:
        result = sdk.config()
        print(f"    Result: {result}")
        assert isinstance(result, dict), "Config should return a dict"
        print("    PASSED")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test exchange_rates
    print("\n[3] Testing exchange_rates()...")
    try:
        result = sdk.exchange_rates()
        print(f"    Result: {result}")
        assert "exchange_rate" in result or isinstance(result, dict), "Should return exchange rates"
        print("    PASSED")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test max_escrow_time
    print("\n[4] Testing max_escrow_time()...")
    try:
        result = sdk.max_escrow_time()
        print(f"    Result: {result}")
        assert "seconds" in result, "Should return seconds"
        assert "minutes" in result, "Should return minutes"
        assert "hours" in result, "Should return hours"
        print("    PASSED")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test fee
    print("\n[5] Testing fee()...")
    try:
        result = sdk.fee()
        print(f"    Result: {result}")
        assert "fee_pct" in result, "Should return fee_pct"
        print("    PASSED")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test status (with test escrow ID - may fail if not exists)
    print("\n[6] Testing status()...")
    try:
        result = sdk.status(TEST_ESCROW_ID)
        print(f"    Result: {result}")
        print("    PASSED (or escrow not found)")
    except Exception as e:
        print(f"    SKIPPED (expected if escrow doesn't exist): {e}")

    # Test escrow_info (with test escrow ID - may fail if not exists)
    print("\n[7] Testing escrow_info()...")
    try:
        result = sdk.escrow_info(TEST_ESCROW_ID)
        print(f"    Result: {result}")
        print("    PASSED")
    except Exception as e:
        print(f"    SKIPPED (expected if escrow doesn't exist): {e}")

    # Test request_payment (commented out by default - creates real transactions)
    print("\n[8] Testing request_payment()...")
    print("    SKIPPED (uncomment to test - creates real transactions)")
    # Uncomment to test:
    # try:
    #     result = sdk.request_payment(
    #         amount=0.001,
    #         receiver=TEST_RECEIVER,
    #         email=TEST_EMAIL,
    #         network="blockdag-testnet"
    #     )
    #     print(f"    Result: {result}")
    #     print("    PASSED")
    # except Exception as e:
    #     print(f"    FAILED: {e}")

    # Test webhook (commented out by default)
    print("\n[9] Testing webhook()...")
    print("    SKIPPED (uncomment to test - registers real webhook)")
    # Uncomment to test:
    # try:
    #     result = sdk.webhook(TEST_WEBHOOK_URL, TEST_ESCROW_ID)
    #     print(f"    Result: {result}")
    #     print("    PASSED")
    # except Exception as e:
    #     print(f"    FAILED: {e}")

    sdk.close()
    print("\n" + "=" * 60)
    print("Sync SDK tests completed")
    print("=" * 60)


async def test_async_sdk():
    """Test all asynchronous SDK methods."""
    print("\n" + "=" * 60)
    print("Testing Asynchronous AsyncEscrowBridgeSDK")
    print("=" * 60)

    async with AsyncEscrowBridgeSDK(BASE_URL) as sdk:
        # Test health
        print("\n[1] Testing health()...")
        try:
            result = await sdk.health()
            print(f"    Result: {result}")
            assert result.get("status") == "ok", "Health check failed"
            print("    PASSED")
        except Exception as e:
            print(f"    FAILED: {e}")

        # Test config
        print("\n[2] Testing config()...")
        try:
            result = await sdk.config()
            print(f"    Result: {result}")
            assert isinstance(result, dict), "Config should return a dict"
            print("    PASSED")
        except Exception as e:
            print(f"    FAILED: {e}")

        # Test exchange_rates
        print("\n[3] Testing exchange_rates()...")
        try:
            result = await sdk.exchange_rates()
            print(f"    Result: {result}")
            assert "exchange_rate" in result or isinstance(result, dict), "Should return exchange rates"
            print("    PASSED")
        except Exception as e:
            print(f"    FAILED: {e}")

        # Test max_escrow_time
        print("\n[4] Testing max_escrow_time()...")
        try:
            result = await sdk.max_escrow_time()
            print(f"    Result: {result}")
            assert "seconds" in result, "Should return seconds"
            print("    PASSED")
        except Exception as e:
            print(f"    FAILED: {e}")

        # Test fee
        print("\n[5] Testing fee()...")
        try:
            result = await sdk.fee()
            print(f"    Result: {result}")
            assert "fee_pct" in result, "Should return fee_pct"
            print("    PASSED")
        except Exception as e:
            print(f"    FAILED: {e}")

        # Test status
        print("\n[6] Testing status()...")
        try:
            result = await sdk.status(TEST_ESCROW_ID)
            print(f"    Result: {result}")
            print("    PASSED (or escrow not found)")
        except Exception as e:
            print(f"    SKIPPED (expected if escrow doesn't exist): {e}")

        # Test escrow_info
        print("\n[7] Testing escrow_info()...")
        try:
            result = await sdk.escrow_info(TEST_ESCROW_ID)
            print(f"    Result: {result}")
            print("    PASSED")
        except Exception as e:
            print(f"    SKIPPED (expected if escrow doesn't exist): {e}")

        print("\n[8] Testing request_payment()...")
        print("    SKIPPED (uncomment to test - creates real transactions)")

        print("\n[9] Testing webhook()...")
        print("    SKIPPED (uncomment to test - registers real webhook)")

    print("\n" + "=" * 60)
    print("Async SDK tests completed")
    print("=" * 60)


def main():
    print(f"Testing SDK against: {BASE_URL}")
    print("Make sure the API server is running!\n")

    # Run sync tests
    test_sync_sdk()

    # Run async tests
    asyncio.run(test_async_sdk())

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
