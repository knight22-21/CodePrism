"""Payment processor module."""

import os
import hashlib
from typing import Optional


class PaymentError(Exception):
    """Raised when a payment fails."""
    pass


class PaymentProcessor:
    """Handles payment processing against a gateway."""

    MAX_RETRY = 3
    DEFAULT_CURRENCY = "USD"

    def __init__(self, gateway_url: str):
        self.gateway_url = gateway_url
        self._session = None

    async def process(self, amount: float, currency: str = "USD") -> bool:
        """Process a payment transaction."""
        if not self._validate(amount):
            raise PaymentError("Invalid amount")
        checksum = compute_checksum(str(amount))
        return await self._submit(amount, currency, checksum)

    def _validate(self, amount: float) -> bool:
        return 0 < amount <= 1_000_000

    async def _submit(self, amount: float, currency: str, checksum: str) -> bool:
        return True


def compute_checksum(data: str) -> str:
    """Compute SHA256 checksum of the given data."""
    return hashlib.sha256(data.encode()).hexdigest()
