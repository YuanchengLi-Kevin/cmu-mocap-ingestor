# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""CLI entrypoint for uploading converted GLBs to Cloudflare R2."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

from features.r2_upload import prepare_uploads, upload_prepared_assets


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MOTIONS = REPOSITORY_ROOT / "data/manifests/motions.json"
DEFAULT_METADATA_DIR = REPOSITORY_ROOT / "data/assets/previews"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "data/manifests/r2_assets.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Upload validated playback and preview GLBs to Cloudflare R2."
    )
    parser.add_argument("--motions", type=Path, default=DEFAULT_MOTIONS)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, help="Upload only the first N converted motions.")
    return parser.parse_args()


def _required_environment(name: str) -> str:
    """Return a required non-empty environment variable."""
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required in the environment or .env file")
    return value


def main() -> None:
    """Validate local assets, upload them, and write the verified manifest."""
    args = parse_args()
    if args.limit is not None and args.output.resolve() == DEFAULT_OUTPUT.resolve():
        raise SystemExit("--limit requires a non-default --output path")

    load_dotenv(REPOSITORY_ROOT / ".env")
    endpoint_url = _required_environment("R2_ENDPOINT_URL")
    bucket = _required_environment("R2_BUCKET_NAME")
    access_key_id = _required_environment("R2_ACCESS_KEY_ID")
    secret_access_key = _required_environment("R2_SECRET_ACCESS_KEY")

    prepared = prepare_uploads(
        REPOSITORY_ROOT,
        args.motions,
        args.metadata_dir,
        args.limit,
    )

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )
    count = upload_prepared_assets(client, bucket, prepared, args.output)
    print(f"Uploaded and verified {count} motions; wrote {args.output}")


if __name__ == "__main__":
    main()
