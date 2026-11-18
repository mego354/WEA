"""
Shared server-side validation helpers for WEA Pharma ERP.
"""

from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError


def parse_positive_integer_quantity(raw_val, *, item_label: str = '', allow_zero: bool = False) -> Decimal:
    """
    Validate and parse a quantity value as an authoritative whole integer.
    Rejects empty, non-numeric, negative, zero (unless allow_zero=True),
    and fractional/decimal quantities without silent rounding or truncation.

    Returns a Decimal with zero fractional part (e.g., Decimal('5')) for
    compatibility with existing DecimalField database columns and calculations.
    """
    prefix = f"الكمية للصنف '{item_label}'" if item_label else "الكمية"

    if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
        raise ValidationError(f"{prefix} مطلوبة ويجب إدخال رقم صحيح.")

    if isinstance(raw_val, bool):
        raise ValidationError(f"{prefix} غير صالحة.")

    cleaned = str(raw_val).strip().replace(',', '')
    try:
        dec_val = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{prefix} يجب أن تكون رقماً صحيحاً صالحاً.")

    if not dec_val.is_finite():
        raise ValidationError(f"{prefix} غير صالحة.")

    if dec_val != dec_val.to_integral_value():
        raise ValidationError(f"{prefix} يجب أن تكون رقماً صحيحاً بدون كسور عشرية (القيمة المدخلة: {cleaned}).")

    int_val = int(dec_val)
    if allow_zero:
        if int_val < 0:
            raise ValidationError(f"{prefix} لا يمكن أن تكون سالبة.")
    else:
        if int_val <= 0:
            raise ValidationError(f"{prefix} يجب أن تكون رقماً صحيحاً أكبر من الصفر.")

    if int_val > 10_000_000:
        raise ValidationError(f"{prefix} تتجاوز الحد الأقصى المسموح به.")

    return Decimal(int_val)
