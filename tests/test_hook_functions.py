import os
import sys

# TraceRecorder'ı projeden dahil edebilmek için
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from TraceRecorder import TraceContext

def inner_math_operation(x, y):
    """Bu fonksiyon hedeflenen `process_data` içerisinden çağrıldığı için 
    otomatik olarak (scope depth > 0) trace edilecektir."""
    res = x * y
    return res + 2

def process_data(data):
    """Bu fonksiyon HEDEF (Target) olarak belirlenmiştir."""
    results = []
    for item in data:
        val = inner_math_operation(item, 10)
        results.append(val)
    return results

def main_workflow():
    """Bu fonksiyon hedef dışıdır. İçerisindeki değişkenler ve satırlar 
    XML'e kaydedilmeyecek, filtreye takılacaktır."""
    raw_data = [1, 2, 3] # AI bunu görmeyecek
    final_result = process_data(raw_data) # Sadece process_data'nın içine girince hook başlayacak
    return final_result


def my_another_function(p1, p2):
    """Bu fonksiyonu da target'a eklediğim için trace ediecek"""
    result = p1 * p2
    print("Sonuç:", result)
    return result

if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    
    print("Test: Fonksiyon Hedefleme (Hook) - TraceContext kullanılarak...")
    
    # Sadece process_data ve onun alt çağrıları kaydedilir. XML formatında çıktı alınır.
    with TraceContext(
        output_format="xml",
        target_functions=["process_data", "my_another_function"], 
        detail_level="detailed"
    ):
        main_workflow()
        my_another_function(3, 7) # Bu fonksiyon da trace edilecek çünkü target_functions'a ekledik
        
    print("Tamamlandı. Çıktıyı inceleyin: output/test_hook_functions.xml")