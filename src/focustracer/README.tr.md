# FocusTracer Türkçe Kullanım Kılavuzu

FocusTracer, Python projelerinde belirli fonksiyonlara odaklanarak XML trace üreten, LLM yönlendirmeli bir dynamic slicing aracıdır. İlk fazda ana amaç, seçilen odak noktaları için `schema v2.1` uyumlu XML log üretmek ve bunu CLI üzerinden kullanılabilir hale getirmektir.

## 1. Kurulum

Proje kökünde:

```bash
pip install -e .
```

Kurulumdan sonra CLI şu şekilde çalışır:

```bash
python -m focustracer --help
```

## 2. Temel Kavramlar

- `target function`: Trace’in hangi fonksiyon çağrısında aktive olacağını belirler.
- `scope`: XML içinde bir fonksiyon çağrısının tamamını temsil eder.
- `loop compaction`: `for` ve `while` döngülerini tekrarlı satır listesi yerine `<loop>` yapısı altında sıkıştırır.
- `target manifest`: Kullanıcı ve/veya LLM tarafından seçilen hedeflerin birleşik JSON karşılığıdır.
- `thread filter`: Aktive olmuş scope içinde sadece belirli thread adlarını kaydetmek için kullanılır.

İlk fazda aktivasyon callable tabanlıdır. Yani sadece `--file` veya `--line` vererek tracing başlatılmaz; en az bir `--function` hedefi gerekir.

## 3. Ollama Durumunu Kontrol Etme

FocusTracer, lokal Ollama servisine bağlanabilir. Önce servis ve model görünürlüğünü kontrol etmek iyi olur.

```bash
python -m focustracer check-agent \
  --agent ollama \
  --model qwen2.5:3b \
  --ollama-url http://localhost:11434
```

Beklenen çıktı JSON formatındadır:

```json
{
  "ok": true,
  "base_url": "http://localhost:11434",
  "model": "qwen2.5:3b",
  "model_available": true,
  "available_models": ["qwen2.5:3b"]
}
```

OpenCode CLI kontrolü için:

```bash
python -m focustracer check-agent \
  --agent opencode \
  --model opencode/minimax-m2.5-free \
  --opencode-cmd opencode
```

## 4. Manuel Hedeflerle Trace Alma

En temel kullanım:

```bash
python -m focustracer run \
  --target-script tests/fixtures/cli_sample_app.py \
  --function worker
```

Bu komut:

- hedef script’i çalıştırır
- `worker` fonksiyonuna girildiğinde trace’i aktive eder
- XML trace dosyası üretir
- kullanılan target manifest’i ayrı bir `.targets.json` dosyası olarak yazar
- XML çıktısını doğrular

Belirli thread adına göre daraltmak için:

```bash
python -m focustracer run \
  --target-script tests/fixtures/cli_sample_app.py \
  --function worker \
  --thread-name CLI-Worker \
  --output output/worker_trace.xml
```

## 5. LLM ile Hedef Önerisi Alma

LLM’e proje envanteri çıkarılıp “hangi fonksiyonlara odaklanayım?” diye sorulabilir.

Varsayılan davranışta `suggest-targets` hedef scripti çalıştırmaz, bu yüzden XML trace üretmez.
Tek komutta trace üretmek için `--execute` kullanılabilir.

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Worker akışı ve multiply davranışı önemli"
```

Öneri manifestini dosyaya yazmak için:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --save-manifest
```

Belirli dosya yoluna yazmak için:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --manifest-output output/cli_sample_app.targets.json
```

Tek komutta öneri + trace için:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Worker akışı ve multiply davranışı önemli" \
  --execute \
  --trace-output output/auto_from_suggest.xml
```

Bu komut şu türde bir JSON döndürür:

```json
{
  "functions": [
    "cli_sample_app.multiply",
    "cli_sample_app.worker"
  ],
  "files": [],
  "lines": [],
  "thread_names": [
    "CLI-Worker"
  ]
}
```

## 6. LLM + Kullanıcı Hedeflerini Birleştirerek Çalıştırma

`--auto-targets` verildiğinde FocusTracer önce LLM’den hedef önerisi alır, sonra bunu kullanıcı tarafından girilen hedeflerle `union` mantığında birleştirir.

```bash
python -m focustracer run \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --auto-targets \
  --function worker \
  --hint "Worker akışı ve multiply davranışı önemli" \
  --output output/auto_trace.xml
```

Bu durumda:

- kullanıcı hedefleri korunur
- LLM’in eklediği hedefler de manifest’e eklenir
- sonuçta tek bir birleşik target manifest ile tracing yapılır

## 7. CLI Parametreleri

### Ortak parametreler

- `--agent`: `ollama` veya `opencode`
- `--model`: varsayılan `qwen2.5:3b`
- `--ollama-url`: varsayılan `http://localhost:11434`
- `--opencode-cmd`: varsayılan `opencode`

### `suggest-targets` için ek parametreler

- `--execute`: öneri sonrası tracing'i otomatik başlatır
- `--save-manifest`: önerilen manifesti dosyaya yazar
- `--manifest-output`: manifestin yazılacağı dosya yolu
- `--output-dir`: `--save-manifest` için klasör (varsayılan `output`)
- `--trace-output`: `--execute` sırasında XML trace dosya yolu
- `--trace-output-dir`: `--execute` sırasında otomatik trace adı klasörü
- `--schema-version`, `--detail`, `--max-depth`, `--max-iterations`, `--skip-validate`: `--execute` için trace ayarları

### `run` komutu için önemli parametreler

- `--target-script`: çalıştırılacak Python script’i
- `--project-root`: envanter çıkarılacak proje kökü
- `--function`: trace aktivasyon hedefi
- `--file`: aktive olmuş scope içinde dosya filtresi
- `--line`: aktive olmuş scope içinde satır filtresi, örn. `pkg/app.py:42`
- `--thread-name`: aktive olmuş scope içinde thread adı filtresi
- `--auto-targets`: LLM hedef önerisini açar
- `--hint`: LLM için kısa yönlendirme
- `--error-context`: hata mesajı veya log bağlamı
- `--output`: XML çıktı dosyası
- `--output-dir`: varsayılan çıktı klasörü
- `--schema-version`: varsayılan `2.1`
- `--detail`: `minimal`, `normal`, `detailed`
- `--max-depth`: maksimum çağrı derinliği
- `--max-iterations`: XML’e yazılacak loop iterasyonu sayısını sınırlar
- `--skip-validate`: XML doğrulamasını atlar

## 8. Üretilen Dosyalar

`run` komutu genellikle iki dosya üretir:

1. XML trace
2. target manifest JSON

Örnek:

```text
output/
├── sample_trace.xml
└── sample_trace.targets.json
```

Manifest dosyası, trace koşusunun hangi hedeflerle çalıştığını sonradan incelemek için özellikle yararlıdır.

`suggest-targets` ise varsayılan olarak sadece terminale JSON yazar. Dosyaya yazmak için `--save-manifest` veya `--manifest-output` kullanılmalıdır.
`--execute` verilirse aynı komutta XML trace de üretilir.

## 9. XML Yapısı

İlk fazda XML şeması `2.1` olarak üretilir. Başlıca yapılar:

- `<thread>`: thread bazlı gruplama
- `<scope>`: fonksiyon çağrısı scope’u
- `<loop>`: kompakt döngü temsili
- `<summary>`: döngü boyunca değişen değişkenlerin özeti

Örnek parça:

```xml
<thread id="..." name="CLI-Worker">
  <scope function="worker" file="...">
    <scope function="process" file="...">
      <loop line="11" source="for value in values:" iterations="3" type="for">
        <iteration index="0">
          <event ... />
        </iteration>
        <summary>
          <variable_changes name="value" initial="1" final="3" change_count="3"/>
        </summary>
      </loop>
    </scope>
  </scope>
</thread>
```

## 10. Python İçinden Kullanım

CLI dışında doğrudan Python API ile de kullanılabilir:

```python
from focustracer import TraceContext


def process(values):
    total = 0
    for value in values:
        total += value
    return total


with TraceContext(
    output_file="output/programmatic.xml",
    schema_version="2.1",
    target_functions=["process"],
    enable_threading=True,
):
    process([1, 2, 3])
```

## 11. Sık Karşılaşılan Durumlar

### `No module named focustracer.__main__`

Eski paket yüzeyinde görülürdü. Yeni sürümde `python -m focustracer` desteklenir. Kurulumdan sonra tekrar deneyin:

```bash
pip install -e .
```

### `Error: at least one target is required`

İlk faz tasarımı gereği en az bir function target gerekir. Örnek:

```bash
python -m focustracer run --target-script app.py --function process_data
```

### `model_available: false`

Ollama çalışıyor olabilir ama istenen model yüklenmemiş olabilir. Önce kontrol edin:

```bash
ollama list
```

Gerekirse model çekin:

```bash
ollama pull qwen2.5:3b
```

### Sadece `--file` veya `--line` ile neden çalışmıyor?

Bu filtreler aktive olmuş scope içinde daraltma yapar. İlk fazda tracing’in başlama noktası callable tabanlıdır; bu yüzden önce `--function` gerekir.

## 12. Önerilen Başlangıç Akışı

Yeni bir kullanıcı için pratik sıra:

1. `python -m focustracer check-agent --model qwen2.5:3b`
2. `python -m focustracer suggest-targets --project-root ... --target-script ... --hint "..."`
3. Tek adım isteniyorsa `python -m focustracer suggest-targets ... --execute`
4. Alternatif olarak manuel `--function` ve `--thread-name` ekleyip `run` kullan
5. Üretilen `.xml` ve `.targets.json` dosyalarını incele

## 13. İlgili Dosyalar

- `src/focustracer/cli.py`: CLI komutları
- `src/focustracer/core/recorder.py`: trace toplama ve XML üretimi
- `src/focustracer/core/patcher.py`: runtime monkey patching
- `src/focustracer/core/targeting.py`: target manifest ve kod envanteri
- `src/focustracer/agent/ollama_client.py`: Ollama entegrasyonu
- `src/focustracer/agent/opencode_client.py`: OpenCode CLI entegrasyonu
- `validate.py`: XML doğrulama yardımcıları
