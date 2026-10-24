#!/usr/bin/env python3
"""Build an unmodified selected xemu source using one shared Git object store."""
import argparse
import collections
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
SOURCES = json.loads((ROOT / "sources.json").read_text())


def run(*args, cwd=ROOT, capture=False, env=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def setup():
    for name, spec in SOURCES.items():
        existing = subprocess.run(["git", "remote", "get-url", name], cwd=ROOT,
                                  capture_output=True, text=True)
        if existing.returncode:
            run("git", "remote", "add", name, spec["url"])
        elif existing.stdout.strip() != spec["url"]:
            raise RuntimeError(f"Remote {name} has a different URL; refusing to replace it")


def checkout(source):
    setup()
    spec = SOURCES[source]
    path = LOCAL / "sources" / source
    # Check before fetching: do not change any existing source state on failure.
    if path.exists() and run("git", "status", "--porcelain", "--untracked-files=no",
                             cwd=path, capture=True):
        raise RuntimeError(f"Tracked changes in {path}; preserve them before updating")
    ref = f"refs/remotes/{source}/{spec['branch']}"
    run("git", "-c", "fetch.recurseSubmodules=false", "fetch", "--no-tags", source,
        f"+refs/heads/{spec['branch']}:{ref}")
    revision = run("git", "rev-parse", ref, capture=True)
    if not path.exists():
        run("git", "-c", "submodule.recurse=false", "worktree", "add", "--detach", path, revision)
    elif run("git", "rev-parse", "HEAD", cwd=path, capture=True) != revision:
        run("git", "-c", "submodule.recurse=false", "checkout", "--detach", revision, cwd=path)
    return path, revision


def build_python():
    python = LOCAL / "venv313/bin/python3"
    if not python.exists():
        interpreter = shutil.which("python3.13")
        if not interpreter:
            raise RuntimeError("Install Python 3.13 before building (brew install python@3.13)")
        run(interpreter, "-m", "venv", python.parents[1])
    if subprocess.run([str(python), "-c", "import yaml"], capture_output=True).returncode:
        run(python, "-m", "pip", "install", "-r", ROOT / "requirements-build.txt")
    return python


def app_path(source):
    return LOCAL / "apps" / source / "xemu.app"


def config_path(source):
    return LOCAL / "runtime" / source / "xemu.toml"


def sign(app):
    run("codesign", "--force", "--deep", "--sign", "-", app)


def prepare_app(source, app=None):
    app = app or app_path(source)
    exe = app / "Contents/MacOS/xemu"
    commands = run("otool", "-l", exe, capture=True)
    rpaths = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", commands)
    for path, count in collections.Counter(rpaths).items():
        for _ in range(count - 1):
            run("install_name_tool", "-delete_rpath", path, exe)
    link = app / "Contents/Resources/xemu.toml"
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise RuntimeError(f"Refusing to replace a regular app config: {link}")
    link.symlink_to(config_path(source))
    sign(app)


def adopt(source, source_path, revision, log):
    built = source_path / "dist/xemu.app"
    if not (built / "Contents/MacOS/xemu").is_file():
        raise RuntimeError(f"Build did not produce {built}")
    target = app_path(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name("xemu-new.app")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(built, temporary, symlinks=True)
    prepare_app(source, temporary)
    previous = target.with_name("xemu-previous.app")
    if previous.exists():
        raise RuntimeError(f"Previous replacement was interrupted; inspect {previous}")
    if target.exists():
        target.rename(previous)
    try:
        temporary.rename(target)
    except OSError:
        if previous.exists():
            previous.rename(target)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    exe = target / "Contents/MacOS/xemu"
    with exe.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = {"source": source, "url": SOURCES[source]["url"], "commit": revision,
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "app": str(target), "sha256": digest, "log": str(log)}
    save(LOCAL / "builds" / f"{source}.json", metadata)
    save(LOCAL / "selected.json", {"source": source})
    print(json.dumps(metadata, indent=2))


def build(source, jobs):
    path, revision = checkout(source)
    python = build_python()
    missing = [name for name in ("ninja", "pkg-config", "cmake", "dylibbundler", "greadlink")
               if not shutil.which(name)]
    if missing:
        raise RuntimeError("Missing build tools: " + ", ".join(missing)
                           + ". See README.md for prerequisites.")
    log = LOCAL / "logs" / f"{source}-build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(python.parent) + os.pathsep + env["PATH"]
    print(f"Building {source} at {revision}; log: {log}", flush=True)
    with log.open("w") as output:
        result = subprocess.run(["./build.sh", f"-j{jobs}"], cwd=path, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Build failed ({result.returncode}); inspect {log}")
    adopt(source, path, revision, log)


def gamepads(source):
    libs = app_path(source) / "Contents/Libraries/arm64"
    library = next(iter(libs.glob("libSDL3*.dylib")), None)
    if library is None:
        raise RuntimeError("Build the app before detecting gamepads")
    sdl = ctypes.CDLL(str(library))
    class Guid(ctypes.Structure):
        _fields_ = [("data", ctypes.c_uint8 * 16)]
    sdl.SDL_Init.argtypes = [ctypes.c_uint32]
    sdl.SDL_Init.restype = ctypes.c_bool
    sdl.SDL_GetGamepads.argtypes = [ctypes.POINTER(ctypes.c_int)]
    sdl.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
    sdl.SDL_GetGamepadNameForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetGamepadNameForID.restype = ctypes.c_char_p
    sdl.SDL_GetJoystickGUIDForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetJoystickGUIDForID.restype = Guid
    sdl.SDL_GUIDToString.argtypes = [Guid, ctypes.c_char_p, ctypes.c_int]
    if not sdl.SDL_Init(0x2000):
        raise RuntimeError("SDL could not initialize gamepads")
    try:
        count = ctypes.c_int()
        ids = sdl.SDL_GetGamepads(ctypes.byref(count))
        found = []
        for index in range(count.value):
            guid = ctypes.create_string_buffer(33)
            sdl.SDL_GUIDToString(sdl.SDL_GetJoystickGUIDForID(ids[index]), guid, 33)
            found.append({"name": sdl.SDL_GetGamepadNameForID(ids[index]).decode(),
                          "guid": guid.value.decode()})
        return found
    finally:
        sdl.SDL_Quit()


def clone_file(src, dest):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["cp", "-c", str(src), str(dest)], capture_output=True).returncode:
        shutil.copyfile(src, dest)


def configure(args):
    source = args.source
    media = args.media_root.expanduser().resolve()
    target = config_path(source)
    if target.exists():
        raise RuntimeError(f"Config already exists: {target}. Edit it to preserve existing settings.")
    files = {"bootrom_path": media / "_BIOS (Flash ROM)/Boot ROM (MCPX)/mcpx_1.0.bin",
             "flashrom_path": media / "_BIOS (Flash ROM)/Flash ROM/xbox-4627_debug.bin",
             "dvd_path": media / "Games.ISO" / args.game}
    for path in [*files.values(), args.hdd, args.eeprom]:
        if not path.is_file():
            raise RuntimeError(f"Missing required file: {path}")
    pads = gamepads(source)
    guid = args.gamepad or (pads[0]["guid"] if len(pads) == 1 else None)
    if not guid:
        raise RuntimeError("Specify --gamepad GUID when zero or multiple gamepads are detected")
    files["hdd_path"] = target.parent / "xbox_hdd.qcow2"
    files["eeprom_path"] = target.parent / "eeprom.bin"
    clone_file(args.hdd, files["hdd_path"])
    clone_file(args.eeprom, files["eeprom_path"])
    # JSON basic strings are valid TOML basic strings for these paths.
    q = json.dumps
    renderer = "OPENGL" if source == "official" else "VULKAN"
    text = (f'[general]\nshow_welcome = false\ngames_dir = {q(str(media / "Games.ISO"))}\n'
            f'[input.bindings]\nport1_driver = "usb-xbox-gamepad"\nport1 = {q(guid)}\n'
            'port2_driver = "usb-xbox-gamepad"\nport2 = "keyboard"\n'
            f'[display]\nrenderer = {q(renderer)}\n'
            '[display.quality]\nsurface_scale = 1\n'
            '[display.window]\nstartup_size = "640x480"\nvsync = true\n')
    if source == "michaeljsr":
        text += '[display.vulkan]\ndriver = "moltenvk"\n'
    text += '[sys]\nmem_limit = "128"\n[sys.files]\n'
    text += ''.join(f'{key} = {q(str(value))}\n' for key, value in files.items())
    target.write_text(text)
    save(target.parent / "controller.json", {"detected": pads, "port1_guid": guid})
    prepare_app(source)
    print(target)


def launch(source):
    if source is None:
        source = json.loads((LOCAL / "selected.json").read_text())["source"]
    exe = app_path(source) / "Contents/MacOS/xemu"
    config = config_path(source)
    if not exe.is_file() or not config.is_file():
        raise RuntimeError("Build and configure this source before launching")
    env = os.environ.copy()
    if source == "michaeljsr":
        env["XEMU_BASE_PATH"] = str(config.parent)
    os.execve(str(exe), [str(exe), "-config_path", str(config)], env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Register source remotes without downloading code")
    p = sub.add_parser("build", help="Fetch and compile only the selected source")
    p.add_argument("source", choices=SOURCES)
    p.add_argument("--jobs", type=int, default=6)
    p = sub.add_parser("gamepads", help="Detect SDL gamepads (requires hardware access)")
    p.add_argument("source", choices=SOURCES)
    p = sub.add_parser("configure", help="Create private config and writable media copies")
    p.add_argument("source", choices=SOURCES)
    p.add_argument("--media-root", type=Path, required=True)
    p.add_argument("--hdd", type=Path, required=True)
    p.add_argument("--eeprom", type=Path, required=True)
    p.add_argument("--game", default="OutRun 2 (Europe) (En,Fr,De,Es,It).xiso.iso")
    p.add_argument("--gamepad", help="SDL GUID; auto-detected when exactly one pad is present")
    p = sub.add_parser("launch", help="Launch the selected app with its private config")
    p.add_argument("source", nargs="?", choices=SOURCES)
    args = parser.parse_args()
    if args.command == "setup":
        setup()
    elif args.command == "build":
        if args.jobs < 1:
            parser.error("--jobs must be positive")
        build(args.source, args.jobs)
    elif args.command == "gamepads":
        print(json.dumps(gamepads(args.source), indent=2))
    elif args.command == "configure":
        configure(args)
    elif args.command == "launch":
        launch(args.source)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
