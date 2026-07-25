import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BengaluruRebuildTest(unittest.TestCase):
    def test_rebuild_is_reproducible_and_reconciles(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            for name in ("one", "two"):
                out = Path(directory) / name
                subprocess.run([sys.executable, str(ROOT / "pipelines/bengaluru_rebuild/rebuild.py"), "--repo-root", str(ROOT), "--output", str(out)], check=True, capture_output=True, text=True)
                subprocess.run([sys.executable, str(ROOT / "tests/reconciliation/reconcile_bengaluru.py"), "--staging", str(out)], check=True, capture_output=True, text=True)
                outputs.append(json.loads((out / "run_manifest.json").read_text())["output_hashes"])
            self.assertEqual(outputs[0], outputs[1])

    def test_manifest_inputs_are_explicit_and_hash_locked(self):
        manifest = json.loads((ROOT / "pipelines/bengaluru_rebuild/input_manifest.json").read_text())
        self.assertEqual(manifest["status"], "READY")
        self.assertEqual(set(manifest["inputs"]), {"master", "geometry", "residential"})
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["inputs"].values()))


if __name__ == "__main__":
    unittest.main()
