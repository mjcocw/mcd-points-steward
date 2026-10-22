#!/usr/bin/env python3
"""麦麦积分资产管家 —— 命令行入口。

    python main.py --mock --html out/report.html
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_steward.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
