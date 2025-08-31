# services/fees.py
from decimal import Decimal
from handy.models import PricingRule

def compute_platform_fee(amount: Decimal, category_id=None) -> Decimal:
    rule = PricingRule.objects.filter(active=True, category_id=category_id).first() or \
           PricingRule.objects.filter(active=True, category__isnull=True).first()
    if not rule:
        return (amount * Decimal('0.11')).quantize(Decimal('1.'))  # défaut 11%
    fee = (amount * (rule.fee_percent/Decimal('100'))).quantize(Decimal('1.'))
    return max(fee, Decimal(rule.fee_min_xof))