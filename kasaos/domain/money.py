"""Exact money handling.

All amounts are integers in kuruş (1 TRY = 100 kuruş). Parsing goes through
Decimal so user text never passes through binary floating point.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from kasaos.core.exceptions import ValidationError

MAX_AMOUNT_KURUS = 100_000_000_000  # 1 milyar TL, guards typos
_ALLOWED = re.compile(r"[0-9][0-9.,]*")


def parse_amount(text: str) -> int:
    """Parse Turkish-formatted user input ("1.250,50", "1250.5", "75") to kuruş."""
    raw = (text or "").strip().replace("₺", "").replace("TL", "").replace(" ", "")
    if not raw:
        raise ValidationError("Tutar giriniz.", "amount")
    if not _ALLOWED.fullmatch(raw):
        raise ValidationError("Geçerli bir tutar giriniz (ör. 1.250,50).", "amount")
    if "," in raw:
        # Turkish style: dots are thousands separators, comma is decimal.
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif "." in raw and len(raw.split(".")[1]) == 3:
        # "1.250" is a thousands separator, not 1.25
        raw = raw.replace(".", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValidationError("Geçerli bir tutar giriniz (ör. 1.250,50).", "amount") from None
    if not value.is_finite():
        raise ValidationError("Geçerli bir tutar giriniz.", "amount")
    if value.as_tuple().exponent < -2:
        raise ValidationError("Tutar en fazla 2 ondalık basamak içerebilir.", "amount")
    kurus = int(value * 100)
    if kurus <= 0:
        raise ValidationError("Tutar sıfırdan büyük olmalıdır.", "amount")
    if kurus > MAX_AMOUNT_KURUS:
        raise ValidationError("Tutar izin verilen üst sınırı aşıyor.", "amount")
    return kurus


def format_amount(kurus: int, symbol: bool = True) -> str:
    """Format kuruş as Turkish currency: 1234550 -> '12.345,50 ₺'."""
    sign = "-" if kurus < 0 else ""
    lira, k = divmod(abs(int(kurus)), 100)
    grouped = f"{lira:,}".replace(",", ".")
    text = f"{sign}{grouped},{k:02d}"
    return f"{text} ₺" if symbol else text
