import pytest
from calc_service import calculate_discounted_total

def test_standard_discount():
    # 100 with 10% discount should be 90.0
    assert calculate_discounted_total(100.0, 10.0) == 90.0

def test_vip_discount():
    # 100 with 10% discount + 5% VIP bonus should be 85.0
    assert calculate_discounted_total(100.0, 10.0, is_vip=True) == 85.0

def test_zero_discount():
    assert calculate_discounted_total(100.0, 0.0) == 100.0

def test_invalid_input():
    with pytest.raises(ValueError):
        calculate_discounted_total(-10.0, 10.0)
