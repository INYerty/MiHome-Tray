# SPDX-License-Identifier: GPL-3.0-or-later
"""Source runtime using this app's protected account, without exporting it."""
import os
from pathlib import Path

from app.core import _json_store

os.environ["MIHOME_NATIVE_DIAGNOSTICS"] = "1"
_json_store.data_dir = lambda: Path(os.environ["LOCALAPPDATA"]) / "MiHome-Windows"

import run

raise SystemExit(run.main())
