import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/xemu.py"
spec = importlib.util.spec_from_file_location("toolkit", MODULE)
toolkit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolkit)


class ToolkitGuards(unittest.TestCase):
    def test_packaging_failure_preserves_the_previous_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            source = local / "sources/michaeljsr"
            built = source / "dist/xemu.app/Contents/MacOS/xemu"
            built.parent.mkdir(parents=True)
            built.write_bytes(b"new app")
            with patch.object(toolkit, "LOCAL", local):
                previous = toolkit.app_path("michaeljsr") / "Contents/MacOS/xemu"
                previous.parent.mkdir(parents=True)
                previous.write_bytes(b"working app")
                with patch.object(toolkit, "prepare_app", side_effect=RuntimeError("signing failed")):
                    with self.assertRaisesRegex(RuntimeError, "signing failed"):
                        toolkit.adopt("michaeljsr", source, "revision", local / "build.log")
                self.assertEqual(previous.read_bytes(), b"working app")
                self.assertFalse((local / "selected.json").exists())

    def test_setup_preserves_an_existing_different_remote(self):
        existing = subprocess.CompletedProcess([], 0, "https://example.invalid/other.git\n")
        with patch.object(toolkit.subprocess, "run", return_value=existing), patch.object(toolkit, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "different URL"):
                toolkit.setup()
            run.assert_not_called()

    def test_dirty_source_blocks_fetch_and_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            (local / "sources/michaeljsr").mkdir(parents=True)
            with patch.object(toolkit, "LOCAL", local), patch.object(toolkit, "setup"), \
                    patch.object(toolkit, "run", return_value=" M file.c") as run:
                with self.assertRaisesRegex(RuntimeError, "Tracked changes"):
                    toolkit.checkout("michaeljsr")
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[1], "status")

    def test_fetch_targets_only_the_selected_remote(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            calls = []
            def record(*args, **kwargs):
                calls.append(args)
                return "a" * 40 if args[1] == "rev-parse" else ""
            with patch.object(toolkit, "LOCAL", local), patch.object(toolkit, "setup"), \
                    patch.object(toolkit, "run", side_effect=record):
                path, commit = toolkit.checkout("cosmicsnow")
            fetch = [call for call in calls if "fetch" in call]
            self.assertEqual(len(fetch), 1)
            self.assertIn("cosmicsnow", fetch[0])
            self.assertNotIn("official", fetch[0])
            self.assertNotIn("michaeljsr", fetch[0])
            self.assertEqual(commit, "a" * 40)
            self.assertEqual(path, local / "sources/cosmicsnow")

    def test_config_copies_writable_media_and_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / "private"
            media = root / "Xbox's Media"
            for relative in ["_BIOS (Flash ROM)/Boot ROM (MCPX)/mcpx_1.0.bin",
                             "_BIOS (Flash ROM)/Flash ROM/xbox-4627_debug.bin",
                             "Games.ISO/OutRun 2.xiso.iso"]:
                path = media / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"media")
            hdd, eeprom = root / "seed.qcow2", root / "seed.bin"
            hdd.write_bytes(b"original HDD")
            eeprom.write_bytes(b"original EEPROM")
            args = argparse.Namespace(source="michaeljsr", media_root=media, hdd=hdd,
                                      eeprom=eeprom, game="OutRun 2.xiso.iso", gamepad=None)
            with patch.object(toolkit, "LOCAL", local), patch.object(toolkit, "prepare_app"), \
                    patch.object(toolkit, "gamepads", return_value=[{"guid": "test-guid"}]):
                toolkit.configure(args)
                target = toolkit.config_path("michaeljsr")
                original_config = target.read_bytes()
                conf = tomllib.loads(original_config.decode())
                copied_hdd = Path(conf["sys"]["files"]["hdd_path"])
                self.assertNotEqual(copied_hdd, hdd)
                self.assertEqual(copied_hdd.read_bytes(), hdd.read_bytes())
                self.assertEqual(conf["display"]["renderer"], "VULKAN")
                self.assertEqual(conf["input"]["bindings"]["port1"], "test-guid")
                with self.assertRaisesRegex(RuntimeError, "Config already exists"):
                    toolkit.configure(args)
                self.assertEqual(target.read_bytes(), original_config)
                self.assertEqual(hdd.read_bytes(), b"original HDD")
                self.assertEqual(eeprom.read_bytes(), b"original EEPROM")


if __name__ == "__main__":
    unittest.main()
