"""
Hızlı Başlangıç Örneği
======================
Bu dosya trace_recorder kullanımının en basit örneğini gösterir.

Çalıştırmak için:
    python quick_start.py
"""

from TraceRecorder import TraceContext


def greet(name):
    """Selamlaşma fonksiyonu."""
    message = f"Merhaba, {name}!"
    print(message)
    return message


def calculate(a, b, operation):
    """Basit hesaplama fonksiyonu."""
    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    elif operation == "subtract":
        result = a - b
    else:
        result = None
    
    return result


def main():
    """Ana fonksiyon - programın giriş noktası."""
    print("=" * 50)
    print("TRACE RECORDER - HIZLI BAŞLANGIÇ")
    print("=" * 50)
    
    # Selamlaşma
    greet("Dünya")
    
    # Hesaplamalar
    print(f"\n5 + 3 = {calculate(5, 3, 'add')}")
    print(f"5 * 3 = {calculate(5, 3, 'multiply')}")
    print(f"5 - 3 = {calculate(5, 3, 'subtract')}")
    
    print("\n" + "=" * 50)
    print("Program tamamlandı!")
    print("=" * 50)


if __name__ == "__main__":
    # TRACE BAŞLATMA - EN KOLAY YÖNTEMLİ
    # with bloğu içindeki tüm kod trace edilir
    with TraceContext("quick_start_trace.xml") as tracer:
        main()
    
    # with bloğundan çıkınca otomatik olarak:
    # 1. Trace durdurulur
    # 2. XML dosyasına kaydedilir
    # 3. Özet bilgiler ekrana yazdırılır
    
    print("\n[CREATED] Trace dosyası oluşturuldu: quick_start_trace.xml")
    print("  Bu dosyayı bir XML editörü ile açarak inceleyebilirsiniz.")
