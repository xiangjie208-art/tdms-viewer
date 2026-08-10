from __future__ import annotations

import os
from pathlib import Path
import sys


if getattr(sys, "frozen", False):
    os.environ.setdefault("TDMS_VIEWER_DATA_DIR", str(Path(sys.executable).resolve().parent / "user_data"))

from tdms_fingerprint_viewer.app import main


if __name__ == "__main__":
    raise SystemExit(main())
