# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""CLI entrypoint for building the joined motion manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from features.motion_manifest import build_joined_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MOTION_INDEX = REPOSITORY_ROOT / "data/manifests/motion_index.json"
DEFAULT_BVH_METADATA = REPOSITORY_ROOT / "data/manifests/bvh_metadata.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "data/manifests/motions.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Join the motion index and BVH metadata into one JSON manifest."
    )
    parser.add_argument(
        "--motion-index",
        type=Path,
        default=DEFAULT_MOTION_INDEX,
        help=f"Motion-index manifest (default: {DEFAULT_MOTION_INDEX})",
    )
    parser.add_argument(
        "--bvh-metadata",
        type=Path,
        default=DEFAULT_BVH_METADATA,
        help=f"BVH metadata manifest (default: {DEFAULT_BVH_METADATA})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Joined manifest destination (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    """Build the joined manifest and print its join counts."""
    args = parse_args()
    summary = build_joined_manifest(args.motion_index, args.bvh_metadata, args.output)
    print(
        f"Wrote {summary.total} records to {args.output} "
        f"({summary.matched} matched, {summary.unmatched_bvh} BVH-only, "
        f"{summary.omitted_index} index-only omitted)"
    )


if __name__ == "__main__":
    main()
