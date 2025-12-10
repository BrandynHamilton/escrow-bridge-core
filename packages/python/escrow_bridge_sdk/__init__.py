"""
Escrow Bridge SDK - Python client for the Escrow Bridge API.

This package provides both synchronous and asynchronous clients for interacting
with the Escrow Bridge payment escrow service.
"""

from .sdk import (
    EscrowBridgeSDK,
    AsyncEscrowBridgeSDK,
    RequestPaymentParams,
    WebhookParams,
)

__version__ = "0.1.0"
__all__ = [
    "EscrowBridgeSDK",
    "AsyncEscrowBridgeSDK",
    "RequestPaymentParams",
    "WebhookParams",
]
