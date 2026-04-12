from __future__ import annotations


def run_program() -> dict:
    # Basit demo verisi
    prices = [10, 20, 15]
    discount = 5
    expensive_limit = 50
    expected_label = "cheap"

    # BUG-1: son urunu toplama dahil etmiyor
    subtotal = 0
    for i, price in enumerate(prices):
        if i < len(prices) - 1:
            subtotal += price

    # BUG-2: indirim cikarmak yerine ekleniyor
    total_after_discount = subtotal + discount


    # BUG-3: esik karsilastirmasi ters
    label = "cheap" if total_after_discount >= expensive_limit else "expensive"

    result = {
        "prices": prices,
        "discount": discount,
        "expensive_limit": expensive_limit,
        "subtotal": subtotal,
        "total_after_discount": total_after_discount,
        "label": label,
        "expected_label": expected_label,
        "passed": label == expected_label,
    }
    return result