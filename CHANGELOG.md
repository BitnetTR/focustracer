# Changelog

## [1.5.0] — 2026-07-24 — `reverse` komutu: reverse execution / state rewind

KIO2 dynamic slicing fazı 4 (Stage 3 — Reverse Execution). GA'nın KIO2 adının
diğer yarısı: *"Reverse Execution"*, "rewind/replay", "enhanced state recovery".

### Added
- **`focustracer reverse <trace.xml>`** CLI komutu:
  - `--at-exception` (varsayılan) / `--at-event ID` / `--at-line LINE [--function NAME]`:
    hedef nokta.
  - `--step-back K`: hedeften K satır-event geriye sar (varsayılan 5).
  - `--json PATH`: yeniden kurulan state'(ler)i yan dosyaya yaz.
  - Çıktı: hedefteki state tablosu + **geriye doğru zaman çizelgesi**. Her adımda
    hangi değişkenin geri alındığını gösterir (`undo total: 12 → 6`), çağrı
    sınırlarını da aşarak sarar.
- **`core/reverse.py`** — state reconstructor:
  - Trace'i frame-farkındalıklı yürütür; her satırda frame'in gözlemlenebilir
    state'ini kurar. Detailed modda satırın tam `<locals>` snapshot'ını kullanır
    (kesin; delta offset'i ve loop-header boşluklarını atlar), normal modda
    tersinir `<delta>` biriktirmeye düşer.
  - `reverse_trace`, `Reconstructor`, `state_diff`, `result_to_dict`.
- `tests/test_reverse.py`: exception state recovery, iterasyonlar arası state
  rewind (total 0→2→6), `--at-line`/`--at-event` hedefleri, undo diff, JSON,
  exception yoksa hata.

### Design
- **Şema değişmez, trace'e yazılmaz.** Reconstructed state türetilmiş veridir
  (delta'lar zaten kodluyor); geri yazmak redundant olur ve trace'i şişirir.
  `reverse`, `load` gibi salt-okunur bir sorgu/görüntüleme komutudur; trace
  değişmez kayıt olarak kalır. İstenirse `--json` yan dosyası.
- **Sınır:** değerler string-repr; canlı nesneler değil, gözlemlenebilir state
  geri kurulur — debugging/state-recovery için doğru, deliverable'da böyle konumlanır.

## [1.4.0] — 2026-07-24 — `run`: fonksiyon vermeden otomatik trace-all

### Changed
- **`focustracer run script.py` artık `--function` gerektirmiyor.** Fonksiyon
  hedefi verilmezse (ve `--auto-targets` kullanılmazsa), script'te tanımlı tüm
  fonksiyonlar otomatik trace edilir — kullanıcı fonksiyon ismi girmek zorunda
  değil. Recorder zaten hedefsiz tracing'i destekliyordu; bu değişiklik onu
  kullanıcının script'iyle sınırlayıp (stdlib/3rd-party değil) CLI'deki "en az
  bir hedef gerekli" engelini kaldırıyor. Odaklamak için `--function` hâlâ
  kullanılabilir (büyük programlarda daha küçük çıktı).
  Bilgilendirici bir not yazdırılır: "tracing all N function(s)…".

## [1.3.1] — 2026-07-24 — GUI çıktı düzeltmeleri + slice UX

Kullanıcı geri bildirimi üzerine düzeltmeler.

### Fixed
- **GUI schema 2.1 → 2.3:** `RunTraceRequest`/`SuggestRequest` varsayılan
  `schema_version` "2.1"'di; GUI ile alınan trace'lerde `<reads>` yoktu ve
  slicing bozuk çalışıyordu. Artık 2.3 (detail zaten "detailed"'dı).
- **GUI çıktı yolu:** trace/manifest dosyaları her zaman kurulum içindeki
  `focustracer/src/output`'a yazılıyordu; kullanıcının GUI'de açtığı proje
  yolu yok sayılıyordu. Artık `<project_root>/output/` (yoksa `<cwd>/output/`)
  altına yazılır; `/api/outputs` listesi de oradan okur. Yeni `_output_base`
  yardımcısı bu yolu tek yerden belirler.

### Changed
- **`slice`/`explain` UX:** `--at-exception` sessizce varsayılan olduğundan,
  exception içermeyen bir trace'te "no exception found" mesajı kafa karıştırıcıydı.
  Artık net bir yönlendirme yazılır: `--at LINE[:VAR]` ile belirli bir değeri
  dilimle (örn. `--at 42:total`).

## [1.3.0] — 2026-07-24 — `explain` komutu: slice'tan LLM root-cause

KIO2 dynamic slicing fazı 3 (Stage 4 — Explain). LLM'e ham trace yerine
**slice** verilir: nedensel zincir + her ifadenin okuduğu **çalışma-anı
değerleri**. Böylece küçük yerel bir model (qwen2.5:3b) bile kök nedeni
isabetle bulur. Ölü `analyze_trace()` bu amaçla canlandırıldı.

### Added
- **`focustracer explain <trace.xml>`** CLI komutu:
  - `--at-exception` / `--at [FILE:]LINE[:VAR]`: slice kriteri (slice komutuyla aynı).
  - `--agent`/`--model`/`--ollama-url`/`--opencode-cmd`: LLM seçimi.
  - `--show-context`: modele giden slice context'ini yazdırır (agent gerektirmez, offline).
  - `--error-context`: modele ek bağlam. `--output`: açıklamayı dosyaya yaz.
  - Model çıktısı: (1) kök neden, (2) düz dille nedensel zincir, (3) somut fix.
- **`core/explain.py`**:
  - `build_slice_context(model, result)` — slice'ı çalışma-anı değerleriyle
    kompakt prompt metnine dönüştürür (deterministik, LLM'siz test edilir).
  - `EXPLAIN_SYSTEM_PROMPT`, `explain_slice(agent, model, result, ...)`.
- `tests/test_explain.py`: context içeriği (exception + `b=0` değeri), context'in
  ham trace'ten küçük olması, agent'a context'in ulaşması (fake agent), ve
  `analyze_trace`'in prompt kurulumu (monkeypatch — server gerektirmez).

### Changed
- **`analyze_trace()` repurpose edildi** (`base` + `ollama` + `opencode`): artık
  ham trace+kaynak dosyası yerine hazır **slice_context** alıp `EXPLAIN_SYSTEM_PROMPT`
  ile sarmalıyor. Eski imza (30k karakter XML dump) kaldırıldı — ölü koddu.
- `slicer.Step` artık okuma değerlerini (`values`), `slicer.Frame` exception
  bilgisini (`exception_info`) taşıyor — explanation context için.

## [1.2.0] — 2026-07-24 — `slice` komutu: backward dynamic slicing

KIO2 dynamic slicing fazı 2. Kaydedilmiş bir trace üzerinde, bir *kriterden*
(hata noktası veya değişken) geriye doğru, o değeri gerçekten etkileyen
ifadeleri çıkaran backward dynamic slice — veri + kontrol bağımlılığı
(Korel & Laski 1988; Agrawal & Horgan 1990).

### Added
- **`focustracer slice <trace.xml>`** CLI komutu:
  - `--at-exception`: en içteki exception'ın hata satırından slice (root-cause).
    `--at` verilmezse varsayılan.
  - `--at [FILE:]LINE[:VAR]`: belirli bir değer için slice (örn. `app.py:42:total`).
  - `--no-control`: yalnızca veri bağımlılığı.
  - `--output`: çıktı yolu (varsayılan `<trace>.sliced.xml`, non-destructive).
  - Sonuç `<slice>` elementi olarak XML'e gömülür ve v2.3 XSD'ye karşı doğrulanır.
  - Terminal çıktısı: `◆` kriter, `▸` kontrol, `·` veri.
- **`core/slicer.py`** — slicing motoru:
  - Trace'i frame-farkındalıklı lineer *execution history*'ye düzleştirir.
    Her adımın `uses`'ı `<reads>`'ten, `defs`'i satırın `ast` parse'ından
    (Store + AugAssign target) gelir — `<delta>` kullanılmaz, böylece delta'nın
    bir-event kayması slicing'i etkilemez. Loop header'ları sentezlenir
    (loop target = def, iterable = use).
  - İleri geçişte her use'un *reaching definition*'ı bulunur (aynı frame'de en
    son def). Parametreler in-frame def yoksa çağrı yerine bağlanır
    (interprocedural). Kontrol bağımlılığı, kaynak AST'sinden en yakın çevreleyen
    `if`/`for`/`while` header'ına yapısal olarak bağlanır.
  - Kriterden geriye erişilebilirlik = slice.
- `schema/trace_schema_v2.3.xsd` (iki kopya): `SliceNodeType` gerçekçileştirildi
  (`line` zorunlu, `event_id` opsiyonel — sentetik loop header düğümleri için;
  `function`/`source` opsiyonel attribute'lar okunabilirlik için). `<slice>`
  elementi henüz kullanılmamıştı, değişiklik geriye uyumlu.
- `tests/test_slicer.py`: def/use + control-map birim testleri, kesinlik
  (alakasız ifade dışlanır), kontrol bağımlılığı, `--no-control`, exception
  root-cause, ve sliced XML'in v2.3 doğrulaması.

### Known limitations
- Slicing **statement-seviyesinde** (standart yaklaşım): interprocedural parametre
  bağlantısı çağrı yerinin tüm okumalarını çeker (sound over-approximation) —
  örn. `total += divide(10, v)` çağrısında `b←v` için `total` de dahil olur.
  Değişken-seviyesi kesinlik sonraki bir iş.
- Kontrol bağımlılığı yapısal (lexical nesting) — yapılandırılmış Python için
  doğru; post-dominator tabanlı tam control-dependence değil.

## [1.1.0] — 2026-07-24 — XSD v2.3 + reads (use-set) yakalama

KIO2 dynamic slicing için ilk faz. Backward slicing, çalışan her satırın
*okuduğu* (use) değişkenleri gerektirir; bu sürüm onları trace'e ekler.
Slice hesaplaması (`focustracer slice`) bir sonraki sürümde (v1.2.0) gelecek.

### Added
- **XSD v2.3** (`schema/trace_schema_v2.3.xsd`, `src/focustracer/schema/` kopyası):
  - `<reads>` elementi (satır event'lerinde, opsiyonel): satırın okuduğu
    değişkenler `<read name type>değer</read>` biçiminde. `<delta>` (yazılanlar)
    ile simetrik; XSD sırası `delta → reads → arguments`.
  - `<slice>` elementi (kök `<trace>` altında, opsiyonel) + `SliceType`,
    `SliceNodeType`, `SliceDependencyEnum` (data/control/criterion). Şema
    kelime dağarcığı şimdi tanımlandı; v1.2.0 dolduracak.
  - Tüm yeni alanlar opsiyonel — v2.2 dosyaları v2.2 XSD ile geçerli kalır.
- **Reads yakalama** (`TraceRecorder`): `detailed` mod + schema ≥ 2.3'te her
  satır için okunan değişkenler kaydedilir. İsimler `ast` ile satır kaynağından
  çıkarılır (Name/Load + AugAssign target = read); değerler satır *çalışmadan
  önceki* locals'tan alınır — yani satırın gerçekten okuduğu değerler. Yerel
  scope'ta olmayan isimler (global, builtin, çağrılan fonksiyon adı) atlanır.
- `tests/test_reads_capture.py`: reads içeriği, v2.3 XSD doğrulaması, loader
  round-trip, ve gating (normal mod / schema < 2.3'te reads yok) testleri.

### Changed
- Varsayılan `schema_version`: `2.2` → `2.3` (`TraceRecorder` + `run`/`suggest`
  CLI). `run` zaten varsayılan `--detail detailed` olduğu için trace'ler artık
  kutudan çıktığı gibi slice'a hazır (reads içerir).
- `TraceLoader` artık `<reads>` elementini parse edip event data'ya taşır
  (v1.2.0 slice komutunun XML'i okuması için).

## [1.0.9] — 2026-07-24 — Test paketi ve şema hijyeni

KIO2 (reverse execution & dynamic slicing) geliştirmeleri öncesi temizlik sürümü.
Yeşil bir test paketi, sonraki fazlar için güvenlik ağı sağlar.

### Fixed
- **v1 şema regresyonu:** `TraceRecorder`, tüm sürümlerde `<trace>` üzerine
  `schema_version` attribute'u ve `<schema_version>` metadata child'ı yazıyordu;
  v1 XSD ikisini de reddediyordu. Artık bu alanlar yalnızca 2.x çıktısında yazılır
  (v1 loader, attribute yokluğunda zaten `"1.0"` varsayıyor).
- **Loader call sayımı:** `TraceDocument.event_type_counts()`, v2.x hiyerarşik
  formatta çağrıları saymıyordu (çağrılar `<event type="call">` değil `<scope>`
  olarak kodlanıyor). Artık her `<scope>` bir `call` olarak sayılır; v1 flat
  format ile tutarlı.
- **Kırık test importları:** 10 test/demo dosyasındaki eski
  `from TraceRecorder import ...` importları `from focustracer import ...` olarak
  düzeltildi (paket `src/focustracer` layout'una taşınmıştı).

### Removed
- Kullanılmayan `pymongo` bağımlılığı `pyproject.toml` ve `requirements.txt`'ten
  kaldırıldı (kod tabanında hiçbir referansı yoktu).

### Changed
- `pyproject.toml`'a `[tool.pytest.ini_options]` eklendi: `pythonpath = ["src"]`
  ve `testpaths = ["tests"]` — editable install olmadan da `pytest` çalışır.
- `tests/conftest.py` eklendi: `bug_examples/*` ve `test_hook_*` demo/repro
  script'leri (assert'siz, `__main__` guard'lı) test toplamasından çıkarıldı.

## [Unreleased] — Schema v2.2 + Post-Mortem Debugging

### Added

#### `focustracer load` — Post-Mortem Debugging CLI Komutu
- Yeni `focustracer load <trace.xml>` CLI komutu ile program bittikten sonra
  kayıtlı XML trace dosyaları terminal'de görselleştirilebilir.
- Varsayılan çıktı: `rich` kütüphanesi ile hiyerarşik call tree
  (thread → scope → loop → iteration hiyerarşisi, return değerleri, delta tracking).
- `--summary`: Sadece istatistik tablosu göster (call tree atlanır).
- `--filter-function NAME`: Sadece belirtilen fonksiyon adına ait scope'ları göster.
- `--filter-thread ID_OR_NAME`: Sadece belirtilen thread'e ait eventi göster.
- `--no-validate`: XSD validation'ı atla, dosyayı doğrudan yükle.
- `rich` yüklü değilse düz-metin fallback çalışır.

**Örnek kullanım:**
```bash
focustracer load output/20260412_231749_cli_sample_app.xml
focustracer load output/trace.xml --summary
focustracer load output/trace.xml --filter-function process
focustracer load output/trace.xml --no-validate
```

#### XSD Schema v2.2 (`schema/trace_schema_v2.2.xsd`)
Tüm yeni alanlar **opsiyonel** (`minOccurs="0"` / `use="optional"`) olarak
eklenmiştir. v2.1 ile üretilmiş dosyalar v2.1 XSD ile doğrulanmaya devam eder;
geriye dönük uyumluluk kırılmamıştır.

| Yeni Alan | Element / Type | Açıklama |
|---|---|---|
| `start_time` | `ScopeType` attribute | Fonksiyon çağrısının UNIX timestamp'i |
| `end_time` | `ScopeType` attribute | Fonksiyon return/exception UNIX timestamp'i |
| `duration` | `ScopeType` attribute | `end_time - start_time` (saniye) |
| `start_time` | `IterationType` attribute | İterasyonun başlangıç UNIX timestamp'i |
| `end_time` | `IterationType` attribute | İterasyonun bitiş UNIX timestamp'i |
| `<traceback>` | `ExceptionType` element | `traceback.format_tb()` çıktısı |
| `<targets>` | `MetadataType` element | Hedeflenen fonksiyon/dosya listesi |
| `<source_files>` | `MetadataType` element | Trace edilen kaynak dosyalar |

#### `src/focustracer/core/loader.py` — TraceLoader
- Yeni `TraceLoader` sınıfı: XML trace dosyasını `TraceDocument` Python nesnesine parse eder.
- v1 (düz event) ve v2.x (thread/scope/loop hiyerarşi) formatlarını destekler.
- v2.2 alanlarını (scope timing, traceback, targets) okur.
- `TraceDocument` üzerinde `count_threads()`, `count_scopes()`, `count_loops()`,
  `event_type_counts()` yardımcı metodları.

#### `src/focustracer/core/display.py` — TraceDisplayer
- Yeni `TraceDisplayer` sınıfı: `TraceDocument`'ı `rich` ile terminal'de gösterir.
- Scope timing (ms cinsinden), loop summary (variable: initial→final),
  exception traceback (ilk 6 satır) desteği.

### Changed

#### Default Schema Version: `2.1` → `2.2`
- `TraceRecorder.__init__` default `schema_version`: `"2.1"` → `"2.2"`
- `focustracer run --schema-version` default: `"2.1"` → `"2.2"`
- `focustracer suggest-targets --schema-version` default: `"2.1"` → `"2.2"`

> **Not:** Eski `--schema-version 2.1` flag'i ile hâlâ v2.1 üretmek mümkündür.

#### `src/focustracer/core/recorder.py`
- Exception event'lerinde `traceback.format_tb()` ile tam stack trace yakalanır.
  v2.2 schema ile `<traceback>` olarak XML'e yazılır; v2.1 ve altında yazılmaz.
- Scope node'larına `start_time`, `end_time`, `duration` eklendi.
  v2.2 schema ile `<scope>` attribute'ları olarak yazılır.
- `_build_xml_tree()`: v2.2 schema'da `<metadata>` altına `<targets>` elementi eklenir.
- `traceback` standart kütüphane import'u eklendi.

### Tests

- `tests/test_xsd_validation.py`: v2.2 için 5 yeni test eklendi
  (simple function, loop compaction, exception traceback, scope timing, threading).
- `tests/test_loader.py`: Yeni test dosyası — `TraceLoader` için 13 unit test
  (temel yükleme, hiyerarşi, v2.2 scope timing, v2.2 exception traceback,
  v2.2 targets metadata, hata işleme, fixture uyumluluğu).
- `src/focustracer/validate/validator.py`: Docstring güncellendi (v2.2 eklendi).

---

## Migration Notes

### v2.1 → v2.2

Mevcut v2.1 trace dosyaları **değişmeden** kullanılabilir:
- `focustracer load output/v2.1_trace.xml` — validator otomatik olarak v2.1 XSD seçer.
- `focustracer run` ile yeni üretilen dosyalar varsayılan olarak v2.2 olur.
- Eski schema ile üretmek için: `focustracer run --schema-version 2.1 ...`

### Validator Fallback Davranışı

`validator.py`, `schema_version` attribute'una göre XSD dosyasını dinamik seçer:
1. `schema/trace_schema_v{version}.xsd` — örn: `trace_schema_v2.2.xsd`
2. Bulunamazsa major version fallback: `trace_schema_v{major}.xsd` — örn: `trace_schema_v2.xsd`
