"""
XSD Validation Tests
====================
TraceContext tarafından üretilen XML dosyalarının XSD şemalarına
uygunluğunu doğrular (v1, v2, v2.1).
"""

import tempfile
import threading
import unittest
from pathlib import Path

from focustracer import TraceContext
from focustracer.validate.validator import validate_xml_against_xsd


class XSDValidationTests(unittest.TestCase):

    def _assert_valid(self, xml_path: Path) -> None:
        is_valid, errors = validate_xml_against_xsd(str(xml_path))
        self.assertTrue(is_valid, f"XSD doğrulama başarısız:\n" + "\n".join(errors))

    # --- v2.1 schema tests ---------------------------------------------------

    def test_simple_function_trace_validates_v21(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "simple.xml"

            def target(x, y):
                result = x + y
                return result

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.1",
                target_functions=["target"],
            ):
                target(3, 4)

            self._assert_valid(out)

    def test_loop_compaction_validates_v21(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "loop.xml"

            def target():
                total = 0
                for i in range(10):
                    total += i
                return total

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.1",
                target_functions=["target"],
                max_iterations=3,
            ):
                target()

            self._assert_valid(out)

    def test_nested_call_trace_validates_v21(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested.xml"

            def helper(n):
                return n * 2

            def target(data):
                return [helper(x) for x in data]

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.1",
                target_functions=["target"],
            ):
                target([1, 2, 3])

            self._assert_valid(out)

    def test_exception_trace_validates_v21(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "exception.xml"

            def target():
                x = 1
                raise ValueError("test error")

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.1",
                target_functions=["target"],
            ):
                try:
                    target()
                except ValueError:
                    pass

            self._assert_valid(out)

    def test_thread_trace_validates_v21(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "thread.xml"

            def worker():
                total = 0
                for i in range(3):
                    total += i

            t = threading.Thread(target=worker, name="Worker-Test")
            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.1",
                enable_threading=True,
                target_functions=["worker"],
                target_thread_names=["Worker-Test"],
            ):
                t.start()
                t.join()

            self._assert_valid(out)

    # --- v2 schema tests -----------------------------------------------------

    def test_simple_function_trace_validates_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "simple_v2.xml"

            def target(values):
                return sum(values)

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.0",
                target_functions=["target"],
            ):
                target([1, 2, 3])

            self._assert_valid(out)

    def test_loop_compaction_validates_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "loop_v2.xml"

            def target():
                n = 5
                while n > 0:
                    n -= 1
                return n

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="2.0",
                target_functions=["target"],
                max_iterations=2,
            ):
                target()

            self._assert_valid(out)

    # --- v1 schema tests -----------------------------------------------------

    def test_simple_function_trace_validates_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "simple_v1.xml"

            def target(a, b):
                return a - b

            with TraceContext(
                output_file=str(out),
                output_format="xml",
                schema_version="1.0",
                target_functions=["target"],
            ):
                target(10, 3)

            self._assert_valid(out)


if __name__ == "__main__":
    unittest.main()
