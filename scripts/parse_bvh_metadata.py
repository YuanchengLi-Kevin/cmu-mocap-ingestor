# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Extract structural and motion metadata from CMU BVH files."""

from __future__ import annotations

import argparse
from pathlib import Path

from cmu_mocap_ingestor.bvh import write_bvh_metadata_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPOSITORY_ROOT / "data/source/cmu-mocap/data"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "data/manifests/bvh_metadata.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract metadata from every CMU BVH file into one JSON manifest."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"BVH data directory (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON manifest destination (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    """Generate and write the BVH metadata manifest."""
    args = parse_args()
    record_count, valid_count = write_bvh_metadata_manifest(args.input, args.output)
    print(f"Wrote {record_count} records to {args.output} ({valid_count} valid)")


if __name__ == "__main__":
    main()
