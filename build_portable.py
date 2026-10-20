# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a portable Windows application with source and license notices."""
from pathlib import Path
import os
import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from importlib import metadata


ROOT = Path(__file__).resolve().parent
manifest = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
if manifest["project"]["name"] != "mihome-windows" or not (ROOT / "app/ui/icon.ico").is_file():
    raise SystemExit("Unexpected project; refusing to build")
for output in (ROOT / "dist", ROOT / "build"):
    if not output.resolve().is_relative_to(ROOT):
        raise SystemExit("Build output resolves outside the project")

args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
        "--name", "MiHome-Tray", "--icon", str(ROOT / "app/ui/icon.ico"),
        "--collect-data", "qtawesome", "--collect-all", "mijiaAPI",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtPdf", "--exclude-module", "pytest",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build/portable-isolated"),
        "--specpath", str(ROOT / "build")]
for name in ("icon.png", "icon.ico", "tray_icon.png", "tray_icon_light.png"):
    args.extend(["--add-data", f"{ROOT / 'app/ui' / name};app/ui"])
args.extend(["--add-data", f"{ROOT / 'app/siui/LICENSE'};app/siui", str(ROOT / "run.py")])
# Qt 6 uses Windows ICU exports. A development PATH containing Poppler/Conda
# can make the collector pick an incompatible, same-named ICU DLL instead.
build_env = os.environ.copy()
windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
build_env["PATH"] = os.pathsep.join([
    str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
    str(windows / "System32"), str(windows),
])
subprocess.run(args, cwd=ROOT, env=build_env, check=True)

folder = ROOT / "dist/MiHome-Tray"
icu = folder / "_internal/icuuc.dll"
if icu.exists():
    import pefile
    binary = pefile.PE(str(icu))
    symbols = {s.name for s in binary.DIRECTORY_ENTRY_EXPORT.symbols}
    if b"ucnv_open" not in symbols:
        raise SystemExit("Incompatible ICU DLL collected; refusing to package")

# A successful freezer exit does not establish that a GUI program starts.
# Check the actual executable before producing the distributable archive.
diagnostic = ROOT / "build/packaged-startup.json"
diagnostic.unlink(missing_ok=True)
diagnostic_env = os.environ.copy()
diagnostic_env["MIHOME_SELF_TEST_OUTPUT"] = str(diagnostic)
if os.name == "nt":
    diagnostic_env["QT_QPA_PLATFORM"] = "windows"
subprocess.run([str(folder / "MiHome-Tray.exe"), "--self-test"], cwd=ROOT,
               env=diagnostic_env, check=True, timeout=25,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
result = json.loads(diagnostic.read_text("utf-8"))
if result.get("version") != manifest["project"]["version"] or not result.get("icons_loaded"):
    raise SystemExit("Packaged startup check failed")
print("Packaged startup check passed", flush=True)
for name in ("LICENSE", "README.md", "README.local.md", "THIRD_PARTY_NOTICES.md"):
    shutil.copy2(ROOT / name, folder / name)
shutil.copytree(ROOT / "docs", folder / "docs", dirs_exist_ok=True)
licenses = folder / "third-party-licenses"
licenses.mkdir(exist_ok=True)
for dist in metadata.distributions():
    name = dist.metadata.get("Name", "unknown").replace("/", "_")
    for entry in dist.files or []:
        if not any(token in str(entry).lower() for token in ("license", "copying")):
            continue
        path = Path(dist.locate_file(entry))
        if path.is_file() and path.suffix.lower() not in (".py", ".pyc", ".exe", ".dll"):
            dest = licenses / name / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
shutil.copy2(ROOT / "packaging/languages/LICENSE", licenses / "Chinese-translation-MIT.txt")
freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], cwd=ROOT, text=True)
freeze = "\n".join(line for line in freeze.splitlines() if not line.startswith(("-e ", "# Editable")))
(ROOT / "requirements-lock.txt").write_text(freeze + "\n", encoding="utf-8")
shutil.copy2(ROOT / "requirements-lock.txt", folder / "requirements-lock.txt")

source = ROOT / "dist/MiHome-Tray-source.zip"
tracked = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
    for relative in tracked:
        path = ROOT / relative
        if path.is_file() and path.suffix not in (".dpapi", ".tmp"):
            archive.write(path, relative)
shutil.copy2(source, folder / source.name)
shutil.make_archive(str(ROOT / "dist/MiHome-Tray-portable"), "zip", root_dir=ROOT / "dist", base_dir="MiHome-Tray")
print(f"Portable application: {folder / 'MiHome-Tray.exe'}")
