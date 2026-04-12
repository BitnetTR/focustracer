import os
import sys

# Proje ana dizinini path'e ekle (TraceRecorder ve auto_debugger'a erişim için)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from TraceRecorder import TraceContext, trace_function
from focustracer.debugger_app.config import DebugConfig
from focustracer.debugger_app.runner import TraceRunner

# =====================================================================
# SEVİYE 1: Kolay - Decorator ile Manuel Fonksiyon Hedefleme (Hook)
# Sadece başına @trace_function yazdığımız yer ve onun içinden 
# çağrılanlar kaydedilir. Geri kalanı göz ardı edilir.
# =====================================================================

def utils_helper(x):
    return x * 10

@trace_function(output_file="output/hook_level1_decorator.jsonl", output_format="jsonl")
def target_function_decorator(x):
    y = utils_helper(x)
    z = y + 5
    return z

def ordinary_function():
    # Bu fonksiyon trace edilmeyecek çünkü decorator'ı yok
    # ve trace bloğu dışında çağrılıyor.
    return 99

def run_level1():
    print("Seviye 1: Decorator testi çalışıyor...")
    ordinary_function()
    target_function_decorator(5)
    print("✓ Seviye 1 tamamlandı. Çıktı: output/hook_level1_decorator.jsonl\n")


# =====================================================================
# SEVİYE 2: Orta - with bloğu ile Dinamik Fonksiyon Hedefleme
# Ana kodu değiştirmeden sadece ilgilendiğimiz bir fonksiyonun 
# ismini target_functions'a verebiliyoruz.
# =====================================================================

def func_a(val):
    # Bu detay kaydedilmeyecek
    return val * 2

def func_b(val):
    # SADECE BU kaydedilecek
    sonuc = val + 5
    return sonuc

def func_c(val):
    # Bu da kaydedilmeyecek
    return func_a(val) + func_b(val)

def run_level2():
    print("Seviye 2: Dinamik Context (TraceContext) testi çalışıyor...")
    
    # Sadece func_b'nin içini kaydetmek istiyoruz.
    with TraceContext(
        output_file="output/hook_level2_context.jsonl", 
        output_format="jsonl",
        target_functions=["func_b"]
    ):
        # Hepsi çağrılacak ama sadece func_b trace edilecek
        func_c(10)
        
    print("✓ Seviye 2 tamamlandı. Çıktı: output/hook_level2_context.jsonl\n")


# =====================================================================
# SEVİYE 3: İleri - Auto Debugger Runner üzerinden Agent Tarzı
# Bir AI Agent koda hiç `with` veya `@trace...` eklemeden
# dışarıdan filtreli (hook) çalıştırabilir.
# =====================================================================

def user_algorithm():
    # Uzun ve karmaşık bir işlem
    total = 0
    for i in range(3):
        total += hidden_sub_task(i)
    return total

def hidden_sub_task(n):
    # Agent sadece buradaki davranışları takip etmek isteyebilir
    hesap = n * n
    return hesap

def run_level3():
    print("Seviye 3: AI Agent tarzı (Dışarıdan Hook / TraceRunner) çalışıyor...")
    
    # Agent konfigurasyonu oluştururken doğrudan hedefini verir
    config = DebugConfig(
        output_dir="output",
        output_format="jsonl",
        target_functions=["hidden_sub_task"] # Sadece bunu merak ediyor
    )
    runner = TraceRunner(config=config)
    
    # Runner aracılığı ile başka bir dosya trace ediliyormuş gibi
    # doğrudan user_algorithm çalıştırılır.
    runner.run(
        source_file=__file__, 
        functions=["user_algorithm()"],
        output_file="output/hook_level3_runner.jsonl",
        exec_mode=False
    )
    print("✓ Seviye 3 tamamlandı. Çıktı: output/hook_level3_runner.jsonl\n")

if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    print("=== Trace Filtering (Hook) Testleri Başlıyor ===\n")
    run_level1()
    run_level2()
    run_level3()
    print("Tüm testler tamamlandı! 'output' klasöründeki jsonl dosyalarını inceleyebilirsiniz.")
