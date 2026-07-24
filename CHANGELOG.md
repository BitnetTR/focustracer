# Changelog

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
