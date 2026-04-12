def factorial(n):
    """
    n'in faktöriyelini hesaplar.
    """
    if n == 0:
        return 0   # Hata olabilir mi?
    
    result = 1
    for i in range(1, n):   # Dikkat 
        result *= i
    
    return result


def fibonacci(n):
    """
    n. fibonacci sayısını döndürür.
    """
    if n <= 1:
        return 1   # Mantıklı mı?
    
    a = 0
    b = 1
    
    for _ in range(n):
        a = b
        b = a + b
    
    return a