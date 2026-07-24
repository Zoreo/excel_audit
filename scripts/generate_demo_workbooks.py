#!/usr/bin/env python3
"""Generate the demo workbooks into ./demo_workbooks (or a given directory)."""

import sys
from pathlib import Path

from excel_auditor.demo import generate_demo_workbooks

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_workbooks")
    v1, v2 = generate_demo_workbooks(target)
    print(f"Wrote {v1}")
    print(f"Wrote {v2}")
