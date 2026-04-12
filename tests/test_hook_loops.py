import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from TraceRecorder import TraceContext

def compute_series(limit):
    """
    Hedef fonksiyon (hook). Döngülerin trace şemasındaki compaction 
    (sıkıştırma) davranışını test etmek için kullanılıyor.
    """
    total = 0
    # For döngüsü (XML'de <loop> tag'ine döner)
    for i in range(limit):
        temp = i * 2
        total += temp
        
    n = limit
    # While döngüsü
    while n > 0:
        total -= 1
        n -= 1
        
    return total

def outer_caller():
    # Bu kısmı trace harici bırakmak hedeftir
    return compute_series(15) # 15 adım sürecek, loop çok uzun olabilir

if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    print("Test: Döngü ve Döngü Sıkıştırması (Loop Compaction) - XML Çıktısı...")
    
    # max_iterations belirterek, her bir döngüyü XML'e sadece 3 adıma kadar kaydeder
    # (Örn: 15 adımlık döngünün sadece ilk 3'ü listelenir ama `summary` node'unda hepsi özetlenir)
    with TraceContext(
        output_file="output/test_hook_loops.xml",
        output_format="xml",
        max_iterations=3, 
        target_functions=["compute_series"]
    ):
        outer_caller()
        
    print("Tamamlandı. Çıktıyı inceleyin: output/test_hook_loops.xml")