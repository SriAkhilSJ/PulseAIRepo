"""Calculator Service with an intentional discount bug for Phase 9.3.2 benchmark."""

def calculate_discounted_total(subtotal: float, discount_percent: float, is_vip: bool = False) -> float:
    """Calculate total after discount. VIP customers receive an additional 5% discount."""
    if subtotal < 0 or discount_percent < 0 or discount_percent > 100:
        raise ValueError("Invalid subtotal or discount percentage")
    total_discount = discount_percent
    if is_vip:
        total_discount += 5.0
    # BUG: Adds discount to subtotal instead of subtracting it!
    return round(subtotal * (1.0 + total_discount / 100.0), 2)
