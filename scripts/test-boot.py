#!/usr/bin/env python3
"""Run a bounded MichaelJSr boot probe against private writable copies."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib

import xemu


class Qmp:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(15)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile("rwb", buffering=0)
        self.greeting = self.read()
        self.serial = 0
        self.request("qmp_capabilities")

    def read(self):
        line = self.stream.readline()
        if not line:
            raise RuntimeError("QMP connection closed")
        return json.loads(line)

    def request(self, command, arguments=None):
        self.serial += 1
        body = {"execute": command, "id": self.serial}
        if arguments is not None:
            body["arguments"] = arguments
        self.stream.write((json.dumps(body) + "\n").encode())
        while True:
            reply = self.read()
            if reply.get("id") == self.serial:
                if "error" in reply:
                    raise RuntimeError(json.dumps(reply["error"]))
                return reply.get("return")

    def close(self):
        self.stream.close()
        self.socket.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()
    if args.seconds < 30:
        parser.error("--seconds must be at least 30")
    root = xemu.ROOT
    source = root / ".local/sources/michaeljsr"
    config = xemu.config_path("michaeljsr")
    data = tomllib.loads(config.read_text())
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = root / ".local/tests" / stamp
    out.mkdir(parents=True, exist_ok=False)
    for key, name in [("hdd_path", "hdd.qcow2"), ("eeprom_path", "eeprom.bin")]:
        xemu.clone_file(Path(data["sys"]["files"][key]), out / name)
    text = config.read_text()
    for key, name in [("hdd_path", "hdd.qcow2"), ("eeprom_path", "eeprom.bin")]:
        old = json.dumps(data["sys"]["files"][key])
        text = text.replace(f"{key} = {old}", f"{key} = {json.dumps(str(out / name))}")
    (out / "xemu.toml").write_text(text)
    app = out / "xemu-test.app"
    shutil.copytree(xemu.app_path("michaeljsr"), app, symlinks=True)
    portable = app / "Contents/Resources/xemu.toml"
    if portable.is_symlink():
        portable.unlink()
    portable.symlink_to(out / "xemu.toml")
    xemu.run("plutil", "-replace", "CFBundleIdentifier", "-string",
             "local.xemu.toolkit.boot-test", app / "Contents/Info.plist")
    xemu.sign(app)
    # Use the selected fork's documented lease/marker/priority policy.
    spec = importlib.util.spec_from_file_location("xemu_lease", source / "scripts/xemu_lease.py")
    lease = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lease)
    env = os.environ.copy()
    env["XEMU_BASE_PATH"] = str(out / "cache")
    env["XEMU_OWNER_DEMO_WAIT"] = "0"
    report = {"source": json.loads((root / ".local/builds/michaeljsr.json").read_text()),
              "config": str(out / "xemu.toml"), "samples": []}
    print(out, flush=True)
    with tempfile.TemporaryDirectory(prefix="xemu-qmp-", dir="/tmp") as temporary:
        qmp_path = Path(temporary) / "qmp.sock"
        command = [str(app / "Contents/MacOS/xemu"), "-config_path", str(out / "xemu.toml"),
                   "-qmp", f"unix:{qmp_path},server=on,wait=off"]
        with (out / "runtime.log").open("w") as log:
            with lease.popen(command, purpose="Xemu toolkit OutRun 2 boot test",
                             expected_secs=args.seconds + 60, env=env,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                report["pid"] = proc.pid
                report["command"] = lease.auto_cmd(command)
                xemu.save(out / "result.json", report)
                qmp = None
                try:
                    deadline = time.monotonic() + 60
                    while not qmp_path.exists():
                        if proc.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(f"xemu did not open QMP; see {out / 'runtime.log'}")
                        time.sleep(0.2)
                    qmp = Qmp(qmp_path)
                    started = time.monotonic()
                    for seconds in sorted({min(30, args.seconds), args.seconds}):
                        while time.monotonic() - started < seconds:
                            if proc.poll() is not None:
                                raise RuntimeError("xemu exited before completing the boot probe")
                            time.sleep(0.5)
                        sample = {"elapsed": time.monotonic() - started,
                                  "frame": qmp.request("query-xemu-frame"),
                                  "display": qmp.request("query-xemu-display"),
                                  "input": qmp.request("query-xemu-input-bindings")}
                        filename = out / f"frame-{seconds}.png"
                        qmp.request("screendump", {"filename": str(filename), "format": "png"})
                        if not filename.is_file() or filename.stat().st_size == 0:
                            raise RuntimeError("xemu did not write the rendered screenshot")
                        sample["screenshot"] = str(filename)
                        report["samples"].append(sample)
                        xemu.save(out / "result.json", report)
                        print(json.dumps(sample), flush=True)
                    report["completed"] = True
                except Exception as error:
                    report["completed"] = False
                    report["error"] = str(error)
                    raise
                finally:
                    if qmp is not None:
                        try:
                            qmp.request("quit")
                        except (OSError, RuntimeError):
                            pass
                        qmp.close()
                    if proc.poll() is None:
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                    report["exit_code"] = proc.returncode
                    report["process_reaped"] = True
                    xemu.save(out / "result.json", report)
    print(json.dumps({"completed": report["completed"], "report": str(out / "result.json")}), flush=True)


if __name__ == "__main__":
    main()
