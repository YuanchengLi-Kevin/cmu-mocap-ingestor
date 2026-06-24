# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""CLI entrypoint for parsing the CMU motion index."""

from __future__ import annotations

import argparse
from pathlib import Path

from features.motion_index import write_motion_index_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPOSITORY_ROOT / "data/source/cmu-mocap/cmu-mocap-index-text.txt"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "data/manifests/motion_index.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate a JSON animation manifest from the CMU motion index."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"CMU index file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON manifest destination (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    """Generate and write the animation manifest."""
    args = parse_args()
    record_count = write_motion_index_manifest(args.input, args.output)
    print(f"Wrote {record_count} animation records to {args.output}")


if __name__ == "__main__":
    main()
