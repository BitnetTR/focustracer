"""
Orta Seviye Test Programı
=========================
Daha karmaşık senaryoları test eder:
- Nested fonksiyon çağrıları
- Exception handling
- Recursive fonksiyonlar
- Class kullanımı
"""

from TraceRecorder import TraceContext


class Calculator:
    """Basit hesap makinesi sınıfı."""
    
    def __init__(self, name):
        self.name = name
        self.history = []
    
    def add(self, a, b):
        """Toplama işlemi."""
        result = a + b
        self.history.append(f"add({a}, {b}) = {result}")
        return result
    
    def multiply(self, a, b):
        """Çarpma işlemi."""
        result = a * b
        self.history.append(f"multiply({a}, {b}) = {result}")
        return result
    
    def power(self, base, exponent):
        """Üs alma işlemi."""
        result = base ** exponent
        self.history.append(f"power({base}, {exponent}) = {result}")
        return result


def fibonacci(n):
    """Fibonacci sayısını recursive olarak hesaplar."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def divide_safe(a, b):
    """Güvenli bölme işlemi (exception handling ile)."""
    try:
        result = a / b
        return result
    except ZeroDivisionError as e:
        print(f"Error: Cannot divide by zero - {e}")
        return None


def nested_function_calls():
    """İç içe fonksiyon çağrıları."""
    def inner_function_1(x):
        def inner_function_2(y):
            return y * 2
        return inner_function_2(x + 1)
    
    return inner_function_1(5)


def process_data(data_list):
    """Liste işleme fonksiyonu."""
    results = []
    for item in data_list:
        if item % 2 == 0:
            processed = item * 2
        else:
            processed = item + 1
        results.append(processed)
    return results


def main():
    """Ana test fonksiyonu."""
    print("="*60)
    print("ORTA SEVİYE TEST PROGRAMI")
    print("="*60)
    
    # 1. Class kullanımı
    print("\n1. Calculator Class Test:")
    calc = Calculator("MyCalculator")
    print(f"  Addition: {calc.add(10, 5)}")
    print(f"  Multiplication: {calc.multiply(6, 7)}")
    print(f"  Power: {calc.power(2, 8)}")
    print(f"  History: {calc.history}")
    
    # 2. Recursive fonksiyon
    print("\n2. Fibonacci Test:")
    fib_number = 7
    fib_result = fibonacci(fib_number)
    print(f"  Fibonacci({fib_number}) = {fib_result}")
    
    # 3. Exception handling
    print("\n3. Exception Handling Test:")
    print(f"  10 / 2 = {divide_safe(10, 2)}")
    print(f"  10 / 0 = {divide_safe(10, 0)}")
    
    # 4. Nested functions
    print("\n4. Nested Functions Test:")
    nested_result = nested_function_calls()
    print(f"  Nested result: {nested_result}")
    
    # 5. Liste işleme
    print("\n5. Data Processing Test:")
    test_data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    processed = process_data(test_data)
    print(f"  Original: {test_data}")
    print(f"  Processed: {processed}")
    
    print("\n" + "="*60)
    print("TEST TAMAMLANDI")
    print("="*60)


if __name__ == "__main__":
    # Trace ile programı çalıştır
    with TraceContext("medium_test_trace.xml") as tracer:
        main()
