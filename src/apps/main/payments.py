"""Compatibility imports for payment services moved to ``apps.payments``."""

from apps.payments import (  # noqa: F401
    allocate_registered_client_payment,
    apply_payment_to_sale,
    collect_client_debt,
)
