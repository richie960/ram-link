import json
import tempfile
import unittest
from pathlib import Path

from ramlink_mesh.dashboard import load_config


class DashboardConfigTests(unittest.TestCase):
    def test_relative_token_path_resolves_from_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            cfg = root / "config" / "dashboard.json"
            cfg.write_text(json.dumps({
                "poll_seconds": 1,
                "nodes": [{"name": "phone", "host": "127.0.0.1",
                           "port": 18080, "token_file": "../token.txt"}]
            }), encoding="utf-8")
            parsed = load_config(cfg)
            self.assertEqual(parsed["poll_seconds"], 2)
            self.assertEqual(parsed["nodes"][0]["token_file"], str(root / "token.txt"))

    def test_invalid_port_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "dashboard.json"
            cfg.write_text(json.dumps({
                "nodes": [{"name": "x", "host": "localhost",
                           "port": 70000, "token_file": "token.txt"}]
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "port"):
                load_config(cfg)

    def test_missing_nodes_array_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "dashboard.json"
            cfg.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nodes"):
                load_config(cfg)


if __name__ == "__main__":
    unittest.main()
