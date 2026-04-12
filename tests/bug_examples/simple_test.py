"""
Basit Test Programı
===================
Bu dosya trace_recorder'ın temel işlevlerini test eder.
"""

from TraceRecorder import TraceContext


def sum_of_even(mylist):

    toplam = 0
    print("İşlem başlıyor...")
    for num in mylist:
        if num % 2 == 0:
            toplam = num
            print(f"Bulunan çift sayı: {num}")

    return toplam


if __name__ == "__main__":
    # Trace ile programı çalıştır
    with TraceContext("simple_test_trace.xml") as tracer:
        sayilar = [10, 5, 20, 7, 4]
        sonuc = sum_of_even(sayilar)

        print("-" * 20)
        print(f"Beklenen Sonuç: 34 (10+20+4)")
        print(f"Programın Bulduğu: {sonuc}")
