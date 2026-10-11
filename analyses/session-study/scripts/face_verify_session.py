#!/usr/bin/env python3
"""Print consent-aware Face-B/Face-A risk for a collector session."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import storage  # noqa: E402
from face.worker import risk_for_session  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id")
    parser.add_argument("--data-dir", type=Path,
                        default=Path(os.environ.get("COLLECTOR_DATA_DIR", ROOT / "data")))
    args = parser.parse_args()
    storage.DATA_DIR = args.data_dir
    storage.DB_PATH = args.data_dir / "participants.sqlite"
    storage.SESSIONS_DIR = args.data_dir / "sessions"
    print(json.dumps(risk_for_session(args.session_id), indent=2))


if __name__ == "__main__":
    main()
