# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""CLI entrypoint for importing the joined manifest into PostgreSQL."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from features.postgres import import_motion_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPOSITORY_ROOT / "data/manifests/motions.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create or update PostgreSQL motion rows from the joined manifest."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Joined motion manifest (default: {DEFAULT_INPUT})",
    )
    return parser.parse_args()


def main() -> None:
    """Load configuration and import the joined manifest."""
    args = parse_args()
    load_dotenv(REPOSITORY_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required in the environment or .env file")

    record_count = import_motion_manifest(database_url, args.input)
    print(f"Imported {record_count} records into public.motions")


if __name__ == "__main__":
    main()
