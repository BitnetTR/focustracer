# FocusTracer

FocusTracer is a zero-touch dynamic slicing and XML trace pipeline for AI-assisted Python debugging.

Turkish usage guide: [README.tr.md](./README.tr.md)


| 🎥 AI4Sweng - FocusTracer (Bölüm 1) | 🚀 AI4Sweng - FocusTracer (Bölüm 2) |
| :---: | :---: |
| [![Bölüm 1](https://img.youtube.com/vi/XoAJj4MXodw/hqdefault.jpg)](https://www.youtube.com/watch?v=XoAJj4MXodw) | [![Bölüm 2](https://img.youtube.com/vi/P0XSIVUeN_Y/hqdefault.jpg)](https://www.youtube.com/watch?v=P0XSIVUeN_Y) |


## Slide

<div align="center">
  <a href="./docs/FocusTracer_Sunum.pptx">
  <img width="500" src="https://github.com/user-attachments/assets/b89d0e92-3f80-48ea-9269-730be880a10e" alt="Watch the Presentation">
</a>

</div>


## Quick Start

```bash
pip install -e .
python -m focustracer check-agent --agent ollama --model qwen2.5:3b
python -m focustracer run \
  --target-script tests/fixtures/cli_sample_app.py \
  --function worker
```

## CLI Commands

### `check-agent`

Checks whether the configured agent backend is reachable and whether the selected model can be used.

```bash
python -m focustracer check-agent \
  --agent ollama \
  --model qwen2.5:3b \
  --ollama-url http://localhost:11434
```

OpenCode CLI example:

```bash
python -m focustracer check-agent \
  --agent opencode \
  --model opencode/minimax-m2.5-free \
  --opencode-cmd opencode
```

### `suggest-targets`

Builds a lightweight code inventory and asks the LLM to select trace targets.

By default, `suggest-targets` does not execute the target script, so it does not produce XML trace files.
If you want one-command execution, use `--execute`.

```bash
python -m focustracer suggest-targets \
  --agent ollama \
  --model qwen2.5:3b \
  --ollama-url http://localhost:11434 \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic"
```

To also save the suggested manifest to `output/`:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic" \
  --save-manifest
```

To write it to an explicit file:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --manifest-output output/cli_sample_app.targets.json
```

One-command hint-to-trace flow:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic" \
  --execute \
  --trace-output output/auto_from_suggest.xml
```

### `run`

Runs the target script, writes an XML trace, writes the merged target manifest next to it, and validates the XML.

**No `--function`? It traces everything in the script.** If you give no function
targets (and don't use `--auto-targets`), FocusTracer traces every function
defined in the target script — no need to name them:

```bash
python -m focustracer run --target-script app.py           # trace all functions in app.py
```

Name functions to focus the trace (smaller output on large programs):

```bash
python -m focustracer run \
  --target-script tests/fixtures/cli_sample_app.py \
  --function worker \
  --thread-name CLI-Worker \
  --output output/sample_trace.xml
```

With automatic LLM target selection:

```bash
python -m focustracer run \
  --agent ollama \
  --model qwen2.5:3b \
  --ollama-url http://localhost:11434 \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --auto-targets \
  --hint "Trace the worker path and multiplication logic"
```

### `slice`

Computes a **backward dynamic slice** over a saved trace: the statements that
actually influenced a value on this run (data + control dependencies). Needs a
`detailed`, schema ≥ 2.3 trace (the default for `run`). Writes the slice into a
`<slice>` element in `<trace>.sliced.xml` and re-validates against the v2.3 XSD.

```bash
# Slice from the innermost exception's failing line (root-cause):
python -m focustracer slice output/sample_trace.xml --at-exception

# Slice a specific value: which statements produced `total` at line 42?
python -m focustracer slice output/sample_trace.xml --at app.py:42:total

# Data dependencies only (skip control):
python -m focustracer slice output/sample_trace.xml --at-exception --no-control
```

Output markers: `◆` criterion, `▸` control dependency, `·` data dependency.

### `explain`

Computes a slice and asks an LLM for a **root-cause explanation**. The model is
given the *slice* — the causal chain annotated with runtime values — not the raw
trace, so even a small local model (e.g. `qwen2.5:3b`) can pinpoint the cause.

```bash
# Explain the root cause of an exception:
python -m focustracer explain output/sample_trace.xml \
  --at-exception --model qwen2.5:3b --ollama-url http://localhost:11434

# See exactly what the model receives (works offline):
python -m focustracer explain output/sample_trace.xml --at-exception --show-context

# Explain a specific value, and save the explanation:
python -m focustracer explain output/sample_trace.xml --at app.py:42:total --output rootcause.md
```

The model answers with: (1) root cause, (2) the causal chain in plain language,
(3) a concrete fix. `--show-context` prints the slice context and needs no agent.

### `reverse`

**Reverse execution / state rewind.** Reconstructs the observable program state
at a point (the crash by default) and steps *backward* through the execution,
watching values un-wind — all from the saved trace, no re-run. Read-only: it
does not modify the trace.

```bash
# State at the crash, plus the reverse timeline:
python -m focustracer reverse output/sample_trace.xml --at-exception --step-back 6

# State at a specific event or line:
python -m focustracer reverse output/sample_trace.xml --at-event 18
python -m focustracer reverse output/sample_trace.xml --at-line 42 --function compute

# Dump the reconstructed state(s) to JSON:
python -m focustracer reverse output/sample_trace.xml --at-exception --json rewind.json
```

Example: at each backward step it shows what a variable *un-does*
(`undo total: 12 → 6`), crossing call boundaries as it rewinds. Values are the
observable (string) state each variable showed, not live objects.

## Using Local Ollama Reliably

Recommended bridge flow for CLI-only environments:

```bash
ollama serve
ollama pull qwen2.5:3b
python -m focustracer check-agent --agent ollama --model qwen2.5:3b --ollama-url http://localhost:11434
python -m focustracer suggest-targets --agent ollama --model qwen2.5:3b --ollama-url http://localhost:11434 --project-root tests/fixtures --target-script tests/fixtures/cli_sample_app.py --hint "Trace the worker path and multiplication logic"
```

Notes:
- `suggest-targets` now fails fast when `--model` is not available in Ollama.
- `suggest-targets` now requests JSON-mode output from Ollama and retries once with a compact candidate list when the first answer is ambiguous.
- If the model still returns non-strict JSON or extra prose, FocusTracer applies robust parsing and inventory-based fallback target selection instead of returning an empty manifest.
- Even if `--project-root` is too narrow, FocusTracer still parses `--target-script` directly so autonomous selection can recover at least script-local functions.
- With `--execute`, FocusTracer immediately runs tracing using the merged suggested manifest and writes XML plus `.targets.json` outputs.

## Default Contracts

- Default model: `qwen2.5:3b`
- Default agent: `ollama`
- Default output format: XML
- Default schema version: `2.1`
- Manual and AI targets are merged with union semantics
- Function targets are required for phase 1 activation

## Manual Target Flags

- `--function`: qualified or simple function name
- `--file`: file filter inside activated scopes
- `--line`: line filter in `path/to/file.py:42` format
- `--thread-name`: thread filter inside activated scopes

## Programmatic Usage

```python
from focustracer import TraceContext


def process(data):
    total = 0
    for item in data:
        total += item
    return total


with TraceContext(
    output_file="output/programmatic.xml",
    schema_version="2.1",
    target_functions=["process"],
    enable_threading=True,
):
    process([1, 2, 3])
```

## Main Modules

- `core/recorder.py`: trace capture, scope grouping, loop compaction, XML output
- `core/patcher.py`: runtime monkey patch activation for target callables
- `core/targeting.py`: target manifest and code inventory helpers
- `agent/ollama_client.py`: Ollama health, model listing, target suggestion
- `agent/opencode_client.py`: OpenCode CLI health and target suggestion
- `core/slicer.py`: backward dynamic slicing (data + control dependency) over a trace
- `core/explain.py`: builds the value-annotated slice context and drives LLM root-cause explanation
- `core/reverse.py`: reverse execution — reconstructs observable state and rewinds through a trace
- `cli.py`: `check-agent`, `suggest-targets`, `run`, `load`, `slice`, `explain`, `reverse`

## CLI Reference (Detaylı)

Aşağıda CLI'deki tüm komutlar, parametreler ve örnek kullanımlar eksiksiz olarak listelenmiştir. Her bir parametrenin tipi, varsayılanı ve kısa açıklaması verilmiştir.

**Genel Notlar**
- CLI komutları: `check-agent`, `suggest-targets`, `run`.
- `--agent` seçenekleri: `ollama`, `opencode`.
- Trace dosyaları CLI `run` çalıştırıldığında `--output` ile belirtilen dosyaya ya da belirtilmemişse `--output-dir` (varsayılan `output`) içine timestamp ile yazılır.
- `suggest-targets` varsayılan olarak sadece JSON çıktıyı terminale yazar; trace üretmez.

---

**check-agent**
- Amaç: Seçilen ajanın bağlantısını ve modelin kullanılabilirliğini kontrol eder.
- Kullanım:

```bash
python -m focustracer check-agent \
  --agent ollama \
  --model qwen2.5:3b \
  --ollama-url http://localhost:11434
```

- Parametreler:
  - `--agent` (choices: `ollama`, `opencode`, default: `ollama`) — kullanılacak AI ajanı.
  - `--model` (string, default: `qwen2.5:3b`) — sorgulanacak model ismi.
  - `--ollama-url` (string, default: `http://localhost:11434`) — Ollama endpoint URL.
  - `--opencode-cmd` (string, default: `opencode`) — OpenCode CLI komutu.

Çıktı: JSON sağlık objesi (`ok`, `model_available`, `available_models`, `error` vb.).

---

**suggest-targets**
- Amaç: Proje envanterini çıkartıp LLM'e hangi fonksiyon/dosya/line/thread hedefleneceğini sorar.
- Kullanım:

```bash
python -m focustracer suggest-targets \
  --agent ollama \
  --model qwen2.5:3b \
  --ollama-url http://localhost:11434 \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic"
```

- Gerekli/Önemli parametreler:
  - `--project-root` (path, required) — kod envanteri için proje kökü.
  - `--target-script` (path, required) — çalıştırılacak hedef script (envanter bağlamı).

- Opsiyonel parametreler:
  - `--hint` (string) — LLM'e ek kullanıcı ipucu.
  - `--error-context` (string) — hata/çalışma zamanı bağlamı verilebilir.
  - `--execute` (flag) — öneri tamamlanınca tracing'i otomatik başlatır.
  - `--save-manifest` (flag) — önerilen manifesti `--output-dir` altına timestamp ile yazar.
  - `--manifest-output` (path) — önerilen manifestin doğrudan yazılacağı dosya yolu.
  - `--output-dir` (path, default `output`) — `--save-manifest` için hedef klasör.
  - `--trace-output` (path) — `--execute` sırasında XML trace dosya yolu.
  - `--trace-output-dir` (path, default `output`) — `--execute` sırasında otomatik trace adı için klasör.
  - `--schema-version`, `--detail`, `--max-depth`, `--max-iterations`, `--skip-validate` — `--execute` sırasında trace çalıştırma ayarları.
  - Hedef filtreleri (hepsi çoklu kullanılabilir): `--function`, `--file`, `--line`, `--thread-name`.

Çıktı: LLM tarafından önerilen hedef manifesti JSON olarak döner; CLI öneriyi yazdırır. `--execute` verilirse trace de üretilir.

---

**run**
- Amaç: Hedef script'i çalıştırıp trace üretmek, manifesti yazmak ve (varsayılan) XML validasyonu yapmak.
- Temel kullanım örneği (manuel fonksiyon hedefiyle):

```bash
python -m focustracer run \
  --target-script tests/fixtures/cli_sample_app.py \
  --function worker \
  --thread-name CLI-Worker \
  --output output/sample_trace.xml
```

- AI ile otomatik hedef seçimi örneği:

```bash
python -m focustracer run \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --auto-targets \
  --hint "Trace the worker path and multiplication logic"
```

- Tüm parametreler (eksiksiz):
  - `--agent` (choices: `ollama`, `opencode`, default `ollama`) — AI ajanı.
  - `--model` (string, default `qwen2.5:3b`) — model ismi.
  - `--ollama-url` (string, default `http://localhost:11434`) — Ollama base URL.
  - `--opencode-cmd` (string, default `opencode`) — OpenCode CLI komutu.
  - `--project-root` (path, default: target script dizini) — envanter için proje kökü.
  - `--target-script` (path, required) — çalıştırılacak hedef script.
  - `--hint` (string) — AI hedef seçiminde kullanılacak ek ipucu.
  - `--error-context` (string) — hataya dair ek context bilgisi.
  - `--auto-targets` (flag) — AI'den otomatik hedef isteği.
  - `--output` (path) — çıktı trace dosyasının tam yolu (yoksa otomatik adlandırma kullanılır).
  - `--output-dir` (path, default `output`) — otomatik dosya adı üretildiğinde kullanılacak dizin.
  - `--schema-version` (string, default `2.1`) — üretilen trace’in şema versiyonu etiketi.
  - `--detail` (choices: `minimal`, `normal`, `detailed`, default `detailed`) — kaydedilecek detay seviyesi.
  - `--max-depth` (int, default `100`) — stack derinliği korunacak maksimum çağrı derinliği.
  - `--max-iterations` (int, optional) — loop kompaktlamada yazılacak iterasyon limiti.
  - `--skip-validate` (flag) — post-run XML validasyonunu atlar.
  - Hedef filtreleri (hepsi çoklu eklenebilir): `--function`, `--file`, `--line`, `--thread-name`.

---

## Output davranışı ve dosya yerleşimi
- `suggest-targets` varsayılan olarak dosya yazmaz; sadece JSON manifesti stdout'a basar.
- `suggest-targets --save-manifest` ile `output/` altına `.targets.json` dosyası yazılabilir.
- `suggest-targets --manifest-output path.json` ile manifest belirli bir yola yazılabilir.
- `suggest-targets --execute` ile aynı komutta XML trace çalıştırılır; trace çıktısı `--trace-output` veya `--trace-output-dir` ile belirlenir.
- Eğer `--output` sağlanırsa trace o dosyaya yazılır.
- Sağlanmazsa, `--output-dir` (default: `output`) içine zaman damgası ve script adı ile otomatik bir dosya ismi üretilir: `YYYYmmdd_HHMMSS_scriptname.xml`.
- Her çalıştırmada aynı köke karşılık `.targets.json` uzantılı bir hedef manifest dosyası oluşturulur.
- Varsayılan çıktı formatı XML'dir. Programatik kullanımda `TraceRecorder.save(format=...)` ile `json` veya `jsonl` de seçilebilir.

---

## Programatik kullanım (kısa hatırlatma)
- `TraceContext` ve `TraceRecorder` sınıfları programatik kullanım içindir. `TraceContext` context manager olarak `start`/`stop`/`save` döngüsünü yönetir.
- Önemli parametreler (programatik): `output_file`, `schema_version`, `target_functions`, `enable_threading`, `detail_level`, `max_depth`, `max_iterations`.

Örnek:

```python
from focustracer import TraceContext

with TraceContext(
    output_file="output/programmatic.xml",
    schema_version="2.1",
    target_functions=["process"],
    enable_threading=True,
    detail_level="detailed",
):
    process([1,2,3])
```

---

## Hata ayıklama ipuçları
- Trace dosyası oluşmuyorsa önce `--output` ile tam yol verin.
- Eğer `--auto-targets` ile hedef bulunamıyorsa `suggest-targets` ile AI önerisini inceleyin veya manuel `--function` ile hedef verin.
- Ollama bağlantı sorunlarında önce `check-agent` çalıştırın.
- XML validasyon hatalarını görmek için `--skip-validate` ile atlayın, ardından üretilen XML'i `schema/` içindeki XSD ile elle doğrulayın.

---

## Parametre Tablosu (CLI)

| Parametre | Komut(lar) | Tip | Varsayılan | Açıklama | Örnek |
|---|---:|---|---|---|---|
| `--agent` | `check-agent`, `suggest-targets`, `run` | choice | `ollama` | Kullanılacak AI ajanı (`ollama` veya `opencode`). | `--agent opencode` |
| `--model` | all | string | `qwen2.5:3b` | Sorgulanacak model ismi. | `--model qwen2.5:3b` |
| `--ollama-url` | all | string | `http://localhost:11434` | Ollama sunucusunun base URL'si. | `--ollama-url http://localhost:11434` |
| `--opencode-cmd` | all | string | `opencode` | OpenCode CLI komutu. | `--opencode-cmd opencode` |
| `--project-root` | `suggest-targets`, `run` | path | target script dizini | Envanter çıkarma kökü. | `--project-root tests/fixtures` |
| `--target-script` | `suggest-targets`, `run` | path | required | Çalıştırılacak script dosyası. | `--target-script tests/fixtures/cli_sample_app.py` |
| `--hint` | `suggest-targets`, `run` | string | - | AI hedef seçiminde ek kullanıcı ipucu. | `--hint "trace worker"` |
| `--error-context` | `suggest-targets`, `run` | string | - | Hata/çeşitli log bağlamı verisi. | `--error-context "IndexError traceback..."` |
| `--execute` | `suggest-targets` | flag | false | Öneri sonrası tracing'i otomatik başlatır. | `--execute` |
| `--save-manifest` | `suggest-targets` | flag | false | Önerilen manifesti dosyaya yazar. | `--save-manifest` |
| `--manifest-output` | `suggest-targets` | path | - | Önerilen manifestin yazılacağı dosya yolu. | `--manifest-output output/suggested.targets.json` |
| `--trace-output` | `suggest-targets` | path | otomatik | `--execute` sırasında trace XML çıktı yolu. | `--trace-output output/auto.xml` |
| `--trace-output-dir` | `suggest-targets` | path | `output` | `--execute` sırasında otomatik trace adı klasörü. | `--trace-output-dir output` |
| `--auto-targets` | `run` | flag | false | AI'den otomatik hedef seçimi istemek. | `--auto-targets` |
| `--output` | `run` | path | otomatik | Trace çıktısının tam yolu (örn. `output/file.xml`). | `--output output/sample_trace.xml` |
| `--output-dir` | `run` | path | `output` | Otomatik dosya adı üretildiğinde kullanılacak dizin. | `--output-dir traces` |
| `--schema-version` | `run` | string | `2.1` | Üretilen trace için şema versiyonu etiketi. | `--schema-version 2.1` |
| `--detail` | `run` | choice | `detailed` | Detay seviyesi: `minimal`/`normal`/`detailed`. | `--detail normal` |
| `--max-depth` | `run` | int | `100` | Kaydedilecek çağrı derinliği sınırı. | `--max-depth 200` |
| `--max-iterations` | `run` | int | - | Loop kompaktlamada saklanacak iterasyon limiti. | `--max-iterations 10` |
| `--skip-validate` | `run` | flag | false | Post-run XML validasyonunu atlar. | `--skip-validate` |
| `--function` | `suggest-targets`, `run` | multi string | - | Hedef fonksiyon(lar). Nitelikli isim veya kısa isim. | `--function module.worker` |
| `--file` | `suggest-targets`, `run` | multi string | - | Dosya filtreleme (rel/abs). | `--file tests/fixtures/cli_sample_app.py` |
| `--line` | `suggest-targets`, `run` | multi string | - | Satır filtreleri `path/to/file.py:42` formatında. | `--line tests/fixtures/cli_sample_app.py:42` |
| `--thread-name` | `suggest-targets`, `run` | multi string | - | Thread adı filtreleri. | `--thread-name CLI-Worker` |

---

Eğer README içinde başka bir bölümde (ör: Türkçe rehber `README.tr.md`) de benzer genişletme isterseniz, onu da güncelleyebilirim.

