#!/usr/bin/env python3
"""Build consented calm Face-B profiles and optional InsightFace enrollments."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.face.enroll import build_face_a_enrollments, build_face_b_profiles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--face-a", action="store_true",
                        help="Also build InsightFace buffalo_l enrollment from calm video chunks")
    args = parser.parse_args()
    b_profiles = build_face_b_profiles(args.data_dir)
    print(f"Face-B profiles: {len(b_profiles)} participants")
    if args.face_a:
        embeddings = build_face_a_enrollments(args.data_dir)
        print(f"Face-A enrollment embeddings: {len(embeddings)} frames")


if __name__ == "__main__":
    main()
