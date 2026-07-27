# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""CLI entrypoint for importing catalog metadata into PostgreSQL."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from features.postgres import import_catalog

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPOSITORY_ROOT / "data/manifests/motions.json"
DEFAULT_ASSETS_INPUT = REPOSITORY_ROOT / "data/manifests/r2_assets.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create or update PostgreSQL motion and verified asset rows."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Joined motion manifest (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--assets-input",
        type=Path,
        default=DEFAULT_ASSETS_INPUT,
        help=f"Verified R2 asset manifest (default: {DEFAULT_ASSETS_INPUT})",
    )
    return parser.parse_args()


def main() -> None:
    """Load configuration and import the catalog manifests."""
    args = parse_args()
    load_dotenv(REPOSITORY_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required in the environment or .env file")

    motion_count, asset_count = import_catalog(
        database_url,
        args.input,
        args.assets_input,
    )
    print(
        f"Imported {motion_count} records into public.motions "
        f"and {asset_count} records into public.motion_assets"
    )


if __name__ == "__main__":
    main()
