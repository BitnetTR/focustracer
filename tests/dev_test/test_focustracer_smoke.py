from __future__ import annotations

import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from focustracer import TraceContext


class FocusTracerSmokeTests(unittest.TestCase):
    def _parse(self, path: Path) -> ET.Element:
        return ET.parse(path).getroot()

    def test_function_target_scopes_to_selected_function(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "function.xml"

            def helper(value):
                return value * 2

            def selected(data):
                total = []
                for item in data:
                    total.append(helper(item))
                return total

            def outer():
                payload = [1, 2, 3]
                return selected(payload)

            with TraceContext(
                output_file=str(output),
                output_format="xml",
                schema_version="2.1",
                target_functions=["selected"],
            ):
                outer()

            root = self._parse(output)
            self.assertIsNone(root.find(".//scope[@function='outer']"))
            self.assertIsNotNone(root.find(".//scope[@function='selected']"))

    def test_loop_compaction_is_present_in_v21(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "loop.xml"

            def selected():
                total = 0
                for value in range(5):
                    total += value
                return total

            with TraceContext(
                output_file=str(output),
                output_format="xml",
                schema_version="2.1",
                target_functions=["selected"],
                max_iterations=3,
            ):
                selected()

            root = self._parse(output)
            loop = root.find(".//loop")
            self.assertIsNotNone(loop)
            self.assertEqual(loop.get("type"), "for")
            self.assertEqual(loop.get("iterations"), "5")
            self.assertIsNotNone(loop.find("summary"))

    def test_thread_group_contains_thread_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "thread.xml"
            lock = threading.Lock()
            shared: list[int] = []

            def worker():
                for index in range(2):
                    with lock:
                        shared.append(index)

            thread = threading.Thread(target=worker, name="Worker-Alpha")
            with TraceContext(
                output_file=str(output),
                output_format="xml",
                schema_version="2.1",
                enable_threading=True,
                target_functions=["worker"],
                target_thread_names=["Worker-Alpha"],
            ):
                thread.start()
                thread.join()

            root = self._parse(output)
            thread_node = root.find(".//thread")
            self.assertIsNotNone(thread_node)
            self.assertEqual(thread_node.get("name"), "Worker-Alpha")


if __name__ == "__main__":
    unittest.main()
