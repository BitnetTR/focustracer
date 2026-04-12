from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from focustracer.core.targeting import build_code_inventory


def test_build_code_inventory_includes_target_script_outside_project_root() -> None:
    with TemporaryDirectory() as root_dir, TemporaryDirectory() as script_dir:
        root = Path(root_dir)
        target_script = Path(script_dir) / "isolated_app.py"
        target_script.write_text(
            "def worker(value):\n"
            "    return value * 2\n",
            encoding="utf-8",
        )

        inventory = build_code_inventory(project_root=root, target_script=target_script)

        assert "isolated_app.worker" in inventory.functions
