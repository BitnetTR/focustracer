"""
Loop Compaction Tests
=====================
max_iterations parametresi ve loop summary özelliklerini test eder.
Özellikle while döngüsü için doğru summary üretildiğini doğrular.
"""

import sys
import os
import xml.etree.ElementTree as ET
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from TraceRecorder import TraceContext


# --- Helpers ----------------------------------------------------------------

def _parse_trace(path: str) -> ET.Element:
    """XML trace dosyasını parse ederek kök elementi döndür."""
    return ET.parse(path).getroot()


# --- Test functions ---------------------------------------------------------

def test_loop_summary_for_loop(tmp_path):
    """for döngüsünde summary elementi oluşturulmalı ve doğru değerler içermeli."""
    out = str(tmp_path / "for_loop.xml")

    def for_func():
        total = 0
        for i in range(5):
            total += i
        return total

    with TraceContext(out, detail_level="normal", schema_version="2.0") as t:
        for_func()

    root = _parse_trace(out)
    loop = root.find(".//loop")
    assert loop is not None, "Loop elementi bulunamadı"
    assert loop.get("type") == "for"
    assert loop.get("iterations") == "5"

    summary = loop.find("summary")
    assert summary is not None, "Loop summary elementi bulunamadı"

    vc_names = {vc.get("name") for vc in summary.findall("variable_changes")}
    assert "i" in vc_names, "Iterator değişkeni 'i' summary'de olmalı"

    i_vc = next(vc for vc in summary.findall("variable_changes") if vc.get("name") == "i")
    assert i_vc.get("initial") == "0"
    assert i_vc.get("final") == "4"
    assert i_vc.get("change_count") == "5"


def test_loop_summary_while_loop(tmp_path):
    """while döngüsünde summary elementi oluşturulmalı ve doğru değerler içermeli.
    
    Python'da sys.settrace bir satırı çalıştırmadan önce 'line' event'i üretir,
    bu yüzden 'n -= 1' satırının etkisi (n değişikliği) döngü header event'inin
    delta'sında görünür. Bu test, bu durumun doğru şekilde ele alındığını doğrular.
    """
    out = str(tmp_path / "while_loop.xml")

    def while_func():
        n = 3
        while n > 0:
            n -= 1
        return n

    with TraceContext(out, detail_level="normal", schema_version="2.0") as t:
        while_func()

    root = _parse_trace(out)
    loop = root.find(".//loop")
    assert loop is not None, "Loop elementi bulunamadı"
    assert loop.get("type") == "while"

    summary = loop.find("summary")
    assert summary is not None, "While loop summary elementi bulunamadı"

    n_vc = next(
        (vc for vc in summary.findall("variable_changes") if vc.get("name") == "n"),
        None,
    )
    assert n_vc is not None, "Değişken 'n' summary'de olmalı"
    assert n_vc.get("final") == "0", "n'nin final değeri 0 olmalı"
    assert int(n_vc.get("change_count", "0")) == 3, "n 3 kez değişmeli (3→2→1→0)"


def test_max_iterations_limits_written_iterations(tmp_path):
    """max_iterations parametresi XML'e yazılan iteration sayısını sınırlamalı."""
    out = str(tmp_path / "limited.xml")

    def loop_func():
        for _ in range(10):
            pass

    with TraceContext(
        out, detail_level="normal", schema_version="2.0", max_iterations=3
    ) as t:
        loop_func()

    root = _parse_trace(out)
    loop = root.find(".//loop")
    assert loop is not None
    assert loop.get("iterations") == "10", "iterations attribute gerçek sayıyı göstermeli"
    assert len(loop.findall("iteration")) <= 3, "En fazla 3 iteration yazılmalı"


def test_max_iterations_none_writes_all(tmp_path):
    """max_iterations=None ise tüm iterasyonlar yazılmalı."""
    out = str(tmp_path / "all_iters.xml")

    def loop_func():
        for _ in range(6):
            pass

    with TraceContext(
        out, detail_level="normal", schema_version="2.0", max_iterations=None
    ) as t:
        loop_func()

    root = _parse_trace(out)
    loop = root.find(".//loop")
    assert loop is not None
    assert loop.get("iterations") == "6"
    assert len(loop.findall("iteration")) == 6


def test_loop_summary_always_present_with_max_iterations(tmp_path):
    """max_iterations ile truncate edilse bile summary her zaman eklenmeli."""
    out = str(tmp_path / "truncated_with_summary.xml")

    def loop_func():
        total = 0
        for i in range(8):
            total += i
        return total

    with TraceContext(
        out, detail_level="normal", schema_version="2.0", max_iterations=2
    ) as t:
        loop_func()

    root = _parse_trace(out)
    loop = root.find(".//loop")
    assert loop is not None

    summary = loop.find("summary")
    assert summary is not None, "Truncate edilse de summary olmalı"

    i_vc = next(
        (vc for vc in summary.findall("variable_changes") if vc.get("name") == "i"),
        None,
    )
    assert i_vc is not None
    assert i_vc.get("initial") == "0"
    assert i_vc.get("final") == "7", "Summary tüm iterasyonların final değerini göstermeli"
    assert i_vc.get("change_count") == "8"


def test_no_loop_no_summary(tmp_path):
    """Döngü olmayan kodda loop elementi bulunmamalı."""
    out = str(tmp_path / "no_loop.xml")

    def simple_func():
        x = 1
        y = x + 1
        return y

    with TraceContext(out, detail_level="normal", schema_version="2.0") as t:
        simple_func()

    root = _parse_trace(out)
    assert root.find(".//loop") is None, "Döngü olmayan kodda loop elementi olmamalı"


def test_schema_v1_no_loop_compaction(tmp_path):
    """Schema v1'de loop compaction yapılmamalı (flat event list)."""
    out = str(tmp_path / "v1.xml")

    def loop_func():
        for _ in range(4):
            pass

    with TraceContext(out, detail_level="normal", schema_version="1.0") as t:
        loop_func()

    root = _parse_trace(out)
    # v1: flat event list, no loop elements
    assert root.find(".//loop") is None, "v1 schema'da loop elementi olmamalı"
