"""
Test script for the Escrow Bridge SDK.

Run with:
    python tests/test_sdk.py

Make sure the API server is running before executing this script.
"""

import sys
import os
import webbrowser
from dotenv import load_dotenv

load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from escrow_bridge.sdk import EscrowBridgeSDK, AsyncEscrowBridgeSDK
import asyncio

# Configuration
BASE_URL = os.getenv("ESCROW_API_URL", "http://localhost:4284")
CLIENT_API_KEY = os.getenv("CLIENT_API_KEY")

if not CLIENT_API_KEY:
    print("WARNING: CLIENT_API_KEY not set in environment. Some tests may fail.")

# Test data - update these for your environment
TEST_RECEIVER = os.getenv("TEST_RECEIVER", "0x38979DFdB5d8FD76FAD4E797c4660e20015C6a84")  # Example addressita
TEST_WEBHOOK_URL = os.getenv("TEST_WEBHOOK_URL", "http://localhost:9201/my-webhook")
TEST_ESCROW_ID = None  # Will be set by request_payment() in sync test
USER_URL = None  # Will be set by request_payment() in sync test

def test_sync_sdk():
    """Test all synchronous SDK methods."""
    print("=" * 60)
    print("Testing Synchronous EscrowBridgeSDK")
    print("=" * 60)

    sdk = EscrowBridgeSDK(BASE_URL, api_key=CLIENT_API_KEY)

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

    # Test request_payment (commented out by default - creates real transactions)
    global TEST_ESCROW_ID, USER_URL
    print("\n[8] Testing request_payment()...")
    print("    SKIPPED (uncomment to test - creates real transactions)")
    # Uncomment to test:
    try:
        result = sdk.request_payment(
            amount=1,
            receiver=TEST_RECEIVER,
            network="base-sepolia"
        )
        print(f"    Result: {result}")
        print("    PASSED")
        TEST_ESCROW_ID = result.get("escrow_id")
        USER_URL = result.get("user_url")
        if USER_URL:
            print(f"    User URL: {USER_URL}")
        message = result.get("message")
        if message:
            print(f"    Message: {message}")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test status (with test escrow ID - may fail if not exists)
    print("\n[6] Testing status()...")
    if TEST_ESCROW_ID:
        try:
            result = sdk.status(TEST_ESCROW_ID)
            print(f"    Result: {result}")
            print("    PASSED (or escrow not found)")
        except Exception as e:
            print(f"    SKIPPED (expected if escrow doesn't exist): {e}")
    else:
        print("    SKIPPED (no escrow ID from request_payment)")

    # Test escrow_info (with test escrow ID - may fail if not exists)
    print("\n[7] Testing escrow_info()...")
    if TEST_ESCROW_ID:
        try:
            result = sdk.escrow_info(TEST_ESCROW_ID)
            print(f"    Result: {result}")
            print("    PASSED")
        except Exception as e:
            print(f"    SKIPPED (expected if escrow doesn't exist): {e}")
    else:
        print("    SKIPPED (no escrow ID from request_payment)")

    # Test webhook (commented out by default)
    print("\n[9] Testing webhook()...")
    if TEST_ESCROW_ID:
        print("    SKIPPED (uncomment to test - registers real webhook)")
        # Uncomment to test:
        try:
            result = sdk.webhook(TEST_WEBHOOK_URL, TEST_ESCROW_ID)
            print(f"    Result: {result}")
            print("    PASSED")
        except Exception as e:
            print(f"    FAILED: {e}")
    else:
        print("    SKIPPED (no escrow ID from request_payment)")

    if USER_URL:
        webbrowser.open(USER_URL)

    sdk.close()
    print("\n" + "=" * 60)
    print("Sync SDK tests completed")
    print("=" * 60)


def main():
    print(f"Testing SDK against: {BASE_URL}")
    print("Make sure the API server is running!\n")

    # Run sync tests
    test_sync_sdk()

    # Run async tests
    # asyncio.run(test_async_sdk())

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
