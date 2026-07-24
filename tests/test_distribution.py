from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_zipapp import build


class DistributionTests(unittest.TestCase):
    def test_zipapp_contains_current_source_without_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = build(Path(directory) / "doctor.pyz")
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("codex_storage_doctor/filesystem.py", names)
            self.assertIn("codex_storage_doctor/schema.py", names)
            self.assertFalse(
                any("__pycache__" in name or name.endswith(".pyc") for name in names)
            )


if __name__ == "__main__":
    unittest.main()
