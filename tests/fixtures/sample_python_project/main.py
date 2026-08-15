"""Entry point that orchestrates the payment flow."""

from processor import PaymentProcessor, compute_checksum


async def run_payment(amount: float) -> bool:
    """Validate amount, compute checksum, then process payment."""
    checksum = compute_checksum(str(amount))
    processor = PaymentProcessor("https://gateway.example.com")
    return await processor.process(amount)


def main() -> None:
    import asyncio
    result = asyncio.run(run_payment(99.99))
    print("Payment result:", result)
