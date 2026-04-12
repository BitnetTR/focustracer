

def bug_list_comprehension():
    # Hatalı yaklaşım
    multipliers = [lambda x: i * x for i in range(5)]

    # Test edelim: multipliers[2](10) sonucunun 20 olmasını bekliyoruz.
    print(f"Index 2 sonucu: {multipliers[2](10)}") 
    print(f"Index 4 sonucu: {multipliers[4](10)}")
    