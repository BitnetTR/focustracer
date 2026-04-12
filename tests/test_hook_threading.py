import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from TraceRecorder import TraceContext

mutex = threading.Lock()
shared_resource = 0

def worker_task(thread_id, iterations):
    """
    Hedeflenen thread task'ı. Birden fazla thread aynı anda bu koda erişecektir.
    Bu durumda `enable_threading=True` bayrağının XML içerisinde `thread_id` tagleri 
    bırakacağı ve threadler arasında ayrım yapabileceği test edilecektir.
    """
    global shared_resource
    for i in range(iterations):
        with mutex:
            local_copy = shared_resource
            # İşletim sisteminin thread switch yapması için minik bir bekleme
            time.sleep(0.01) 
            shared_resource = local_copy + 1

def run_threads():
    threads = []
    
    # 3 Çalışan (Worker) thread başlat.
    for i in range(3):
        t = threading.Thread(target=worker_task, args=(i, 2), name=f"Worker-{i}")
        threads.append(t)
        t.start()
    
    # Ana thread (main) beklemede
    for t in threads:
        t.join()

if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    print("Test: Multi-Threading ve Mutex Kayıt Hook'u (XML Çıktısı)...")
    
    # Threading işlemlerini kayda alması ve sadece 'worker_task'ın takip edilmesi (Agent)
    with TraceContext(
        output_file="output/test_hook_threading.xml",
        output_format="xml",
        enable_threading=True,  # Bunu true bırakmak önemlidir!
        target_functions=["worker_task"]
    ):
        run_threads()
        
    print("Tamamlandı. Çıktıyı inceleyin: output/test_hook_threading.xml")