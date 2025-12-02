"""
Escrow Bridge SDK - Client for interacting with the Escrow Bridge API.
"""

import httpx
from typing import Optional
from dataclasses import dataclass


@dataclass
class RequestPaymentParams:
    """Parameters for requesting a payment."""
    amount: float
    receiver: str
    email: str
    network: str = "blockdag-testnet"
    api_key: Optional[str] = None


@dataclass
class WebhookParams:
    """Parameters for registering a webhook."""
    webhook_url: str
    escrow_id: str


class EscrowBridgeSDK:
    """
    SDK client for the Escrow Bridge API.

    Usage:
        sdk = EscrowBridgeSDK("http://localhost:8000")

        # Check health
        health = sdk.health()

        # Get exchange rates
        rates = sdk.exchange_rates()

        # Request a payment
        result = sdk.request_payment(
            amount=100.0,
            receiver="0x...",
            email="user@example.com"
        )
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        """
        Initialize the SDK client.

        Args:
            base_url: The base URL of the Escrow Bridge API (e.g., "http://localhost:8000")
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def _get(self, endpoint: str) -> dict:
        """Make a GET request to the API."""
        url = f"{self.base_url}{endpoint}"
        response = self._client.get(url)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict) -> dict:
        """Make a POST request to the API."""
        url = f"{self.base_url}{endpoint}"
        response = self._client.post(url, json=data)
        response.raise_for_status()
        return response.json()

    def status(self, escrow_id: str) -> dict:
        """
        Get the status of an escrow by ID.

        Args:
            escrow_id: The escrow ID (hex string, with or without 0x prefix)

        Returns:
            dict with escrowId and status information
        """
        return self._get(f"/status/{escrow_id}")

    def health(self) -> dict:
        """
        Check the health of the API.

        Returns:
            dict with health status
        """
        return self._get("/health")

    def config(self) -> dict:
        """
        Get the escrow bridge configuration.

        Returns:
            dict mapping network names to their configuration (address, etc.)
        """
        return self._get("/config")

    def escrow_info(self, escrow_id: str) -> dict:
        """
        Get detailed information about an escrow.

        Args:
            escrow_id: The escrow ID (hex string, with or without 0x prefix)

        Returns:
            dict with escrowId and payment details
        """
        return self._get(f"/escrow_info/{escrow_id}")

    def exchange_rates(self) -> dict:
        """
        Get current exchange rates for all supported networks.

        Returns:
            dict with exchange_rate mapping network to rate info
        """
        return self._get("/exchange_rates")

    def max_escrow_time(self) -> dict:
        """
        Get the maximum escrow time allowed.

        Returns:
            dict with seconds, minutes, and hours values
        """
        return self._get("/max_escrow_time")

    def fee(self) -> dict:
        """
        Get the current fee percentage.

        Returns:
            dict with fee_pct value
        """
        return self._get("/fee")

    def request_payment(
        self,
        amount: float,
        receiver: str,
        email: str,
        network: str = "blockdag-testnet",
        api_key: Optional[str] = None
    ) -> dict:
        """
        Request a new payment/escrow.

        Args:
            amount: The payment amount
            receiver: The receiver's wallet address (checksummed)
            email: The user's email address
            network: The network to use (default: "blockdag-testnet")
            api_key: Optional API key for authentication

        Returns:
            dict with tx_hash, id_hash, and network
        """
        payload = {
            "amount": amount,
            "receiver": receiver,
            "email": email,
            "network": network,
        }
        if api_key:
            payload["api_key"] = api_key

        return self._post("/request_payment", payload)

    def webhook(self, webhook_url: str, escrow_id: str) -> dict:
        """
        Register a webhook to be notified when an escrow is completed.

        Args:
            webhook_url: The URL to POST to when the escrow completes
            escrow_id: The escrow ID to watch

        Returns:
            dict with escrowId and status
        """
        payload = {
            "webhook_url": webhook_url,
            "escrowId": escrow_id,
        }
        return self._post("/webhook", payload)


class AsyncEscrowBridgeSDK:
    """
    Async SDK client for the Escrow Bridge API.

    Usage:
        async with AsyncEscrowBridgeSDK("http://localhost:8000") as sdk:
            health = await sdk.health()
            rates = await sdk.exchange_rates()
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        """
        Initialize the async SDK client.

        Args:
            base_url: The base URL of the Escrow Bridge API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def _get(self, endpoint: str) -> dict:
        """Make a GET request to the API."""
        url = f"{self.base_url}{endpoint}"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()

    async def _post(self, endpoint: str, data: dict) -> dict:
        """Make a POST request to the API."""
        url = f"{self.base_url}{endpoint}"
        response = await self._client.post(url, json=data)
        response.raise_for_status()
        return response.json()

    async def status(self, escrow_id: str) -> dict:
        """Get the status of an escrow by ID."""
        return await self._get(f"/status/{escrow_id}")

    async def health(self) -> dict:
        """Check the health of the API."""
        return await self._get("/health")

    async def config(self) -> dict:
        """Get the escrow bridge configuration."""
        return await self._get("/config")

    async def escrow_info(self, escrow_id: str) -> dict:
        """Get detailed information about an escrow."""
        return await self._get(f"/escrow_info/{escrow_id}")

    async def exchange_rates(self) -> dict:
        """Get current exchange rates for all supported networks."""
        return await self._get("/exchange_rates")

    async def max_escrow_time(self) -> dict:
        """Get the maximum escrow time allowed."""
        return await self._get("/max_escrow_time")

    async def fee(self) -> dict:
        """Get the current fee percentage."""
        return await self._get("/fee")

    async def request_payment(
        self,
        amount: float,
        receiver: str,
        email: str,
        network: str = "blockdag-testnet",
        api_key: Optional[str] = None
    ) -> dict:
        """Request a new payment/escrow."""
        payload = {
            "amount": amount,
            "receiver": receiver,
            "email": email,
            "network": network,
        }
        if api_key:
            payload["api_key"] = api_key

        return await self._post("/request_payment", payload)

    async def webhook(self, webhook_url: str, escrow_id: str) -> dict:
        """Register a webhook for escrow completion notification."""
        payload = {
            "webhook_url": webhook_url,
            "escrowId": escrow_id,
        }
        return await self._post("/webhook", payload)
