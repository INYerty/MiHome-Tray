# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile the per-user Windows setup EXE after build_portable.py."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parent
manifest = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
assert manifest["project"]["name"] == "mihome-windows", "Wrong project"
version = manifest["project"]["version"]
folder = ROOT / "dist/MiHome-Tray"
diagnostic = json.loads((ROOT / "build/packaged-startup.json").read_text("utf-8"))
assert diagnostic["version"] == version and diagnostic["icons_loaded"], "Build portable first"
assert (folder / "MiHome-Tray.exe").is_file() and (folder / "MiHome-Tray-source.zip").is_file()

candidates = [os.environ.get("ISCC"), shutil.which("iscc"),
              ROOT / "build/tools/InnoSetup/ISCC.exe",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
              Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6/ISCC.exe"]
compiler = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
if compiler is None:
    raise SystemExit("Install Inno Setup 6.7+ or set ISCC to its compiler executable")
subprocess.run([str(compiler), f"/DAppVersion={version}", str(ROOT / "packaging/windows.iss")],
               cwd=ROOT, check=True)
installer = ROOT / f"dist/MiHome-Tray-Setup-{version}-x64.exe"
assert installer.is_file()
files = [installer, ROOT / "dist/MiHome-Tray-portable.zip", ROOT / "dist/MiHome-Tray-source.zip"]
checksums = "\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files) + "\n"
(ROOT / "dist/SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
print(f"Setup ready: {installer}")
