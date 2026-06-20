"""
SMS parser for DRC airtime network confirmation messages.

Parses sell (outgoing transfer) and purchase (incoming stock) messages
from all 4 networks: Africell, Airtel, Orange, Vodacom.

Sender → Network mapping:
  "Africell"   → AFRICEL
  "1000"       → AIRTEL
  "e-recharge" → ORANGE
  "1449"       → VODACOM

Amounts are returned as integers (units).
Vodacom sends USD ($); conversion: 1 USD = 100 units (fixed network denomination).
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from apps.models import NetworkType, normalize_phone

# 1 Vodacom USD = 100 airtime units (Vodacom's fixed denomination standard in DRC)
VODACOM_USD_TO_UNITS = 100

KNOWN_SENDERS: dict[str, NetworkType] = {
    "africell":   NetworkType.AFRICEL,
    "1000":       NetworkType.AIRTEL,
    "e-recharge": NetworkType.ORANGE,
    "1449":       NetworkType.VODACOM,
}


@dataclass
class ParsedSMS:
    message_type: str                       # "sale" | "purchase" | "unknown"
    network: Optional[NetworkType] = None
    quantity: int = 0                       # in units (always)
    recipient_phone: Optional[str] = None   # normalized +243XXXXXXXXX (sales only)
    client_name: Optional[str] = None       # Vodacom includes recipient name


# ── Per-network regex patterns ────────────────────────────────────────────────

# Africell sell:  "votre transaction de 100000.00 U au 243900952142 U a reussi"
_AFRICEL_SELL = re.compile(
    r"votre transaction de\s*([\d.]+)\s*u\s+au\s+(\d+)",
    re.IGNORECASE,
)

# Africell purchase: "Vous avez recharge 159574.00 u."
_AFRICEL_PURCHASE = re.compile(
    r"avez recharge\s*([\d.]+)\s*u",
    re.IGNORECASE,
)

# Airtel sell:  "5037:Votre transfert de 2500 U au 972067057 a reussi"
_AIRTEL_SELL = re.compile(
    r"transfert de\s*(\d+)\s*u\s+au\s+(\d+)\s+a\s+reussi",
    re.IGNORECASE,
)

# Airtel purchase: "8087:Vous avez recu un stock de :eTopUP:42780 U provenant"
_AIRTEL_PURCHASE = re.compile(
    r"avez recu un stock de\s*:?etopup:(\d+)\s*u",
    re.IGNORECASE,
)

# Orange sell:  "Vous avez transfere 250 U au 840217562"
_ORANGE_SELL = re.compile(
    r"avez transfer[eé]\s*(\d+)\s*u\s+au\s+(\d+)",
    re.IGNORECASE,
)

# Orange purchase: "Vous avez recu 7500 U du 844025889"
_ORANGE_PURCHASE = re.compile(
    r"avez recu\s*(\d+)\s*u\s+du\s+(\d+)",
    re.IGNORECASE,
)

# Vodacom sell:  "Vous venez d'envoyer 5,00 $ a Heritier Kulimushi(830211406)"
_VODACOM_SELL = re.compile(
    r"envoyer\s*([\d,]+(?:\.\d+)?)\s*\$\s+a\s+([^(]+)\((\d+)\)",
    re.IGNORECASE,
)

# Vodacom purchase: "Vous venez de recevoir 107,89 $"
_VODACOM_PURCHASE = re.compile(
    r"venez de recevoir\s*([\d,]+(?:\.\d+)?)\s*\$",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_units(raw: str) -> int:
    """Parse a decimal-or-integer string (dot separator) to integer units."""
    try:
        return int(Decimal(raw))
    except (InvalidOperation, ValueError):
        return 0


def _vodacom_usd_to_units(raw: str) -> int:
    """Convert Vodacom USD string ('5,00' or '107,89') to integer units."""
    try:
        usd = Decimal(raw.replace(",", "."))
        return int(usd * VODACOM_USD_TO_UNITS)
    except (InvalidOperation, ValueError):
        return 0


# ── Public API ────────────────────────────────────────────────────────────────

def parse_sms(sender: str, body: str) -> ParsedSMS:
    """
    Parse a DRC airtime SMS into structured data.

    Returns ParsedSMS with message_type='unknown' when the sender or body
    pattern is not recognized — caller should ignore these silently.
    """
    network = KNOWN_SENDERS.get(sender.strip().lower())
    if network is None:
        return ParsedSMS(message_type="unknown")

    body = body.strip()

    if network == NetworkType.AFRICEL:
        m = _AFRICEL_SELL.search(body)
        if m:
            return ParsedSMS(
                message_type="sale",
                network=network,
                quantity=_to_units(m.group(1)),
                recipient_phone=normalize_phone(m.group(2)),
            )
        m = _AFRICEL_PURCHASE.search(body)
        if m:
            return ParsedSMS(
                message_type="purchase",
                network=network,
                quantity=_to_units(m.group(1)),
            )

    elif network == NetworkType.AIRTEL:
        m = _AIRTEL_SELL.search(body)
        if m:
            return ParsedSMS(
                message_type="sale",
                network=network,
                quantity=int(m.group(1)),
                recipient_phone=normalize_phone(m.group(2)),
            )
        m = _AIRTEL_PURCHASE.search(body)
        if m:
            return ParsedSMS(
                message_type="purchase",
                network=network,
                quantity=int(m.group(1)),
            )

    elif network == NetworkType.ORANGE:
        m = _ORANGE_SELL.search(body)
        if m:
            return ParsedSMS(
                message_type="sale",
                network=network,
                quantity=int(m.group(1)),
                recipient_phone=normalize_phone(m.group(2)),
            )
        m = _ORANGE_PURCHASE.search(body)
        if m:
            return ParsedSMS(
                message_type="purchase",
                network=network,
                quantity=int(m.group(1)),
            )

    elif network == NetworkType.VODACOM:
        m = _VODACOM_SELL.search(body)
        if m:
            return ParsedSMS(
                message_type="sale",
                network=network,
                quantity=_vodacom_usd_to_units(m.group(1)),
                client_name=m.group(2).strip(),
                recipient_phone=normalize_phone(m.group(3)),
            )
        m = _VODACOM_PURCHASE.search(body)
        if m:
            return ParsedSMS(
                message_type="purchase",
                network=network,
                quantity=_vodacom_usd_to_units(m.group(1)),
            )

    return ParsedSMS(message_type="unknown")
