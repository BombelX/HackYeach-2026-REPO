"""Run backend integration tests from any working directory."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "analyses")]
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.discover(str(ROOT / "tests"))
)
raise SystemExit(0 if result.wasSuccessful() else 1)
