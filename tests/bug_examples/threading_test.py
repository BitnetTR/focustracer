"""
Multi-Threading Test Programı
=============================
Thread-safe trace kaydını test eder.
"""

import threading
import time
from TraceRecorder import TraceContext


def worker_task(worker_id, iterations):
    """Worker thread görevi."""
    print(f"Worker {worker_id} started")
    
    for i in range(iterations):
        # Biraz iş yap
        result = compute_something(worker_id, i)
        time.sleep(0.01)  # Kısa bekleme
    
    print(f"Worker {worker_id} finished")


def compute_something(worker_id, value):
    """Basit bir hesaplama."""
    temp = value * 2
    result = temp + worker_id
    return result


def main():
    """Ana thread test fonksiyonu."""
    print("="*60)
    print("MULTI-THREADING TEST")
    print("="*60)
    
    # 3 thread oluştur
    threads = []
    num_threads = 3
    iterations_per_thread = 4
    
    print(f"\nCreating {num_threads} threads...")
    
    for i in range(num_threads):
        thread = threading.Thread(
            target=worker_task,
            args=(i, iterations_per_thread)
        )
        threads.append(thread)
    
    # Thread'leri başlat
    print("Starting threads...")
    for thread in threads:
        thread.start()
    
    # Ana thread'de de biraz iş yap
    print("Main thread doing work...")
    for i in range(3):
        result = compute_something(999, i)
        time.sleep(0.02)
    
    # Thread'lerin bitmesini bekle
    print("Waiting for threads to complete...")
    for thread in threads:
        thread.join()
    
    print("\n" + "="*60)
    print("MULTI-THREADING TEST TAMAMLANDI")
    print("="*60)


if __name__ == "__main__":
    # Trace ile programı çalıştır
    with TraceContext("threading_test_trace.xml") as tracer:
        main()
