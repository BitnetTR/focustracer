# Changelog

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
