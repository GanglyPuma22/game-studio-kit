"""Run from any working directory; keep the complete repository together."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_tools.cli import main

raise SystemExit(main())
