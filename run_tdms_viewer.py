from __future__ import annotations

import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))
os.environ.setdefault("TDMS_VIEWER_DATA_DIR", str(PROJECT_ROOT / "user_data"))

from tdms_fingerprint_viewer.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
