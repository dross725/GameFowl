#!/usr/bin/env python3
"""
Build a ready-to-run embeddable Python 3.12 + pywin32 under local_print_agent/python/.

Run this on a networked Windows build/server machine (amd64) before packaging
or serving the print-agent download zip. Teller PCs stay fully offline.

Usage (from this folder, or any cwd):
  python prepare_vendor.py
  prepare_vendor.bat
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
PYTHON_DIR = AGENT_DIR / "python"
STAGING_DIR = AGENT_DIR / "vendor" / "_staging"
VERSION_FILE = PYTHON_DIR / "VERSION.txt"

# Pin a known-good 3.12 embeddable build. Bump intentionally when upgrading.
PYTHON_VERSION = "3.12.9"
EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)
    print(f"  -> {dest} ({dest.stat().st_size:,} bytes)")


def latest_pywin32_wheel_url() -> tuple[str, str]:
    """Return (filename, download_url) for cp312 win_amd64 pywin32 wheel."""
    api = "https://pypi.org/pypi/pywin32/json"
    print(f"Resolving latest pywin32 wheel from {api}")
    with urllib.request.urlopen(api, timeout=60) as response:
        data = json.load(response)
    version = data["info"]["version"]
    files = data["releases"].get(version) or []
    for item in files:
        name = item.get("filename") or ""
        if name.endswith("-cp312-cp312-win_amd64.whl"):
            return name, item["url"]
    die(f"No cp312 win_amd64 wheel found for pywin32=={version}")


def enable_site_packages(python_dir: Path) -> None:
    pth_files = list(python_dir.glob("python*._pth"))
    if not pth_files:
        die(f"No python*._pth found under {python_dir}")
    pth = pth_files[0]
    text = pth.read_text(encoding="utf-8")
    lines = []
    saw_import_site = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and "import site" in stripped:
            lines.append("import site")
            saw_import_site = True
        elif stripped == "import site":
            lines.append("import site")
            saw_import_site = True
        else:
            lines.append(line)
    if not saw_import_site:
        lines.append("import site")
    # Ensure Lib\\site-packages is on the path for embeddable layouts.
    if not any("site-packages" in line for line in lines):
        lines.append("Lib\\site-packages")
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Enabled site-packages in {pth.name}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print(">", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if check and completed.returncode != 0:
        die(f"Command failed with exit code {completed.returncode}: {' '.join(cmd)}")
    return completed.returncode


def write_version_file(pywin32_wheel: str) -> None:
    python_exe = PYTHON_DIR / "python.exe"
    py_ver = "unknown"
    if python_exe.exists():
        try:
            out = subprocess.check_output(
                [str(python_exe), "-c", "import sys; print(sys.version.split()[0])"],
                text=True,
            ).strip()
            py_ver = out or py_ver
        except (subprocess.CalledProcessError, OSError):
            py_ver = PYTHON_VERSION
    VERSION_FILE.write_text(
        f"python={py_ver}\n"
        f"embed={PYTHON_VERSION}-amd64\n"
        f"pywin32_wheel={pywin32_wheel}\n",
        encoding="utf-8",
    )
    print(f"Wrote {VERSION_FILE}")


def main() -> None:
    if os.name != "nt":
        die(
            "prepare_vendor.py must run on Windows (amd64). "
            "It builds embeddable Python + pywin32 for teller PCs."
        )

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    embed_zip = STAGING_DIR / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    get_pip = STAGING_DIR / "get-pip.py"

    if PYTHON_DIR.exists():
        print(f"Removing existing {PYTHON_DIR}")
        shutil.rmtree(PYTHON_DIR)
    PYTHON_DIR.mkdir(parents=True, exist_ok=True)

    if not embed_zip.exists():
        download(EMBED_URL, embed_zip)
    else:
        print(f"Using cached {embed_zip}")

    print(f"Extracting embeddable Python to {PYTHON_DIR}")
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(PYTHON_DIR)

    enable_site_packages(PYTHON_DIR)

    wheel_name, wheel_url = latest_pywin32_wheel_url()
    wheel_path = STAGING_DIR / wheel_name
    if not wheel_path.exists():
        download(wheel_url, wheel_path)
    else:
        print(f"Using cached {wheel_path}")

    if not get_pip.exists():
        download(GET_PIP_URL, get_pip)
    else:
        print(f"Using cached {get_pip}")

    python_exe = PYTHON_DIR / "python.exe"
    if not python_exe.exists():
        die(f"Missing {python_exe} after extract")

    run([str(python_exe), str(get_pip), "--no-warn-script-location"])
    run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-warn-script-location",
            str(wheel_path),
        ]
    )

    # pywin32 post-install registers DLLs for this interpreter.
    postinstall_ok = run(
        [str(python_exe), "-m", "pywin32_postinstall", "-install"],
        check=False,
    ) == 0
    if not postinstall_ok:
        scripts = PYTHON_DIR / "Scripts"
        candidates = [
            scripts / "pywin32_postinstall.py",
            PYTHON_DIR / "Lib" / "site-packages" / "win32" / "scripts" / "pywin32_postinstall.py",
        ]
        for script in candidates:
            if script.exists():
                run([str(python_exe), str(script), "-install"])
                postinstall_ok = True
                break
        if not postinstall_ok:
            die("pywin32_postinstall failed and script was not found")

    run(
        [
            str(python_exe),
            "-c",
            "import win32print, win32con; print('win32print/win32con: OK')",
        ]
    )
    # win32ui may need VC++ redist; warn but do not fail the prepare.
    ui_check = subprocess.run(
        [str(python_exe), "-c", "import win32ui; print('win32ui: OK')"]
    )
    if ui_check.returncode != 0:
        print(
            "WARNING: win32ui failed to import. "
            "Teller PCs may need VC++ x64 redistributable, "
            "or use print_mode escpos."
        )

    write_version_file(wheel_name)
    print()
    print("Done. Bundled runtime is ready at:")
    print(f"  {PYTHON_DIR}")
    print("Re-run this script after upgrading Python or pywin32 pins.")


if __name__ == "__main__":
    main()
