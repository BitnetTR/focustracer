"""
TraceLoader Tests
=================
focustracer.core.loader.TraceLoader için unit testler.
Gerçek fixture XML dosyasını ve in-memory üretilen trace'leri parse eder.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from focustracer import TraceContext
from focustracer.core.loader import TraceLoader, TraceDocument


class TestTraceLoaderBasic(unittest.TestCase):

    def _make_trace(self, func, schema_version="2.2", **ctx_kwargs) -> Path:
        tmp = tempfile.mkdtemp()
        out = Path(tmp) / "trace.xml"
        with TraceContext(
            output_file=str(out),
            output_format="xml",
            schema_version=schema_version,
            **ctx_kwargs,
        ):
            func()
        return out

    # ------------------------------------------------------------------
    # Basic load & metadata
    # ------------------------------------------------------------------

    def test_load_returns_trace_document(self):
        def target(x, y):
            return x + y

        out = self._make_trace(lambda: target(3, 4), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertIsInstance(doc, TraceDocument)

    def test_schema_version_parsed(self):
        def target():
            return 42

        out = self._make_trace(lambda: target(), schema_version="2.2", target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertEqual(doc.schema_version, "2.2")

    def test_total_events_positive(self):
        def target():
            x = 1
            y = x + 1
            return y

        out = self._make_trace(lambda: target(), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertGreater(doc.total_events, 0)

    def test_total_duration_non_negative(self):
        def target():
            pass

        out = self._make_trace(lambda: target(), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertGreaterEqual(doc.total_duration, 0.0)

    def test_start_end_time_present(self):
        def target():
            pass

        out = self._make_trace(lambda: target(), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertIsNotNone(doc.start_time)
        self.assertIsNotNone(doc.end_time)

    # ------------------------------------------------------------------
    # Hierarchical structure
    # ------------------------------------------------------------------

    def test_scope_nodes_present(self):
        def target(n):
            return n * 2

        out = self._make_trace(lambda: target(5), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertGreater(doc.count_scopes(), 0)

    def test_loop_nodes_present(self):
        def target():
            total = 0
            for i in range(5):
                total += i
            return total

        out = self._make_trace(lambda: target(), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        self.assertGreater(doc.count_loops(), 0)

    def test_thread_nodes_present_when_threading(self):
        def worker():
            x = 1
            return x

        t = threading.Thread(target=worker, name="LoaderTestWorker")

        out = self._make_trace(
            lambda: (t.start(), t.join()),
            enable_threading=True,
            target_functions=["worker"],
            target_thread_names=["LoaderTestWorker"],
        )
        doc = TraceLoader().load(str(out))
        self.assertGreater(doc.count_threads(), 0)

    # ------------------------------------------------------------------
    # v2.2: scope timing
    # ------------------------------------------------------------------

    def test_scope_duration_populated_v22(self):
        def target(n):
            return n * 2

        out = self._make_trace(
            lambda: target(3),
            schema_version="2.2",
            target_functions=["target"],
        )
        doc = TraceLoader().load(str(out))

        def find_scope(nodes):
            for node in nodes:
                if node.get("type") == "scope":
                    return node
                child = find_scope(node.get("children", []))
                if child:
                    return child
            return None

        scope = find_scope(doc.nodes)
        self.assertIsNotNone(scope, "Expected at least one scope node")
        self.assertIsNotNone(scope.get("duration"), "duration should be set for v2.2")
        self.assertGreaterEqual(scope["duration"], 0.0)

    # ------------------------------------------------------------------
    # v2.2: exception traceback
    # ------------------------------------------------------------------

    def test_exception_traceback_captured_v22(self):
        def target():
            raise ValueError("loader test error")

        out = self._make_trace(
            lambda: _call_safely(target),
            schema_version="2.2",
            target_functions=["target"],
        )
        doc = TraceLoader().load(str(out))

        exc_node = _find_exception(doc.nodes)
        self.assertIsNotNone(exc_node, "Expected at least one exception node")
        self.assertEqual(exc_node.get("type"), "ValueError")
        # traceback may be empty if no frame info, but key must exist
        self.assertIn("traceback", exc_node)

    # ------------------------------------------------------------------
    # v2.2: metadata targets
    # ------------------------------------------------------------------

    def test_metadata_targets_v22(self):
        def target():
            return 1

        out = self._make_trace(
            lambda: target(),
            schema_version="2.2",
            target_functions=["target"],
        )
        doc = TraceLoader().load(str(out))
        # targets list should be populated (at least the runtime-resolved name)
        self.assertIsInstance(doc.targets, list)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            TraceLoader().load("/tmp/nonexistent_focustracer_trace.xml")

    def test_invalid_xml_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
            f.write("not xml at all <<<")
            fname = f.name
        with self.assertRaises(ValueError):
            TraceLoader().load(fname)

    # ------------------------------------------------------------------
    # Fixture file (output/ directory)
    # ------------------------------------------------------------------

    def test_load_existing_fixture(self):
        """Mevcut output/ fixture XML'ini yükleyebilmeli."""
        fixture_dir = Path(__file__).resolve().parent.parent / "output"
        xml_files = list(fixture_dir.glob("*.xml"))
        if not xml_files:
            self.skipTest("No fixture XML files found in output/")
        doc = TraceLoader().load(str(xml_files[0]))
        self.assertIsInstance(doc, TraceDocument)
        self.assertGreater(doc.total_events, 0)

    # ------------------------------------------------------------------
    # event_type_counts
    # ------------------------------------------------------------------

    def test_event_type_counts(self):
        def target(n):
            return n + 1

        out = self._make_trace(lambda: target(10), target_functions=["target"])
        doc = TraceLoader().load(str(out))
        counts = doc.event_type_counts()
        self.assertIn("call", counts)
        self.assertIn("return", counts)
        self.assertGreater(counts["call"], 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_safely(func):
    try:
        func()
    except Exception:
        pass


def _find_exception(nodes) -> dict | None:
    for node in nodes:
        ntype = node.get("type")
        if ntype == "scope":
            exc = node.get("exception")
            if exc:
                return exc
            result = _find_exception(node.get("children", []))
            if result:
                return result
        elif ntype in ("thread",):
            result = _find_exception(node.get("children", []))
            if result:
                return result
        elif ntype == "event":
            exc = node.get("data", {}).get("exception")
            if exc:
                return exc
    return None


if __name__ == "__main__":
    unittest.main()
