import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from TraceRecorder import trace_function

# Decorator kullanılarak (manuel) hata fırlatan bir fonksiyonu hook'luyoruz
# Çıktı yine AI'ın rahat okuyabileceği XML (.xml) formatında.
@trace_function(detail_level="normal",  output_format="xml", target_functions=["my_divide"])
def my_divide(a, b):
    x = a + 5
    # Eğer b 0 ise bu satırda exception fırlatılacak ve XML'de <exception> node'u oluşacak
    y = x / b
    return y

def caller():
    try:
        # Başarılı çağrı
        my_divide(10, 2)
        # Hatalı çağrı
        my_divide(20, 0)
    except Exception as e:
        print(f"Ana programda hata yakalandı (Filtre dışı): {e}")

if __name__ == "__main__":

    print("Test: Exception (Hata) Fırlatma ve Hook...")
    caller()
    print("Tamamlandı. Çıktıyı inceleyin: output/test_hook_exceptions.xml")