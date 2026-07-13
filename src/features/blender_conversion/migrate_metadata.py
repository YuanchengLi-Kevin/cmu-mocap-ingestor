# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Migrate preview JSON metadata without running Blender conversion."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from features.blender_conversion.conversion_metadata import migrate_metadata


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_METADATA_DIR = REPOSITORY_ROOT / "data/assets/previews"


def parse_args() -> argparse.Namespace:
    """Parse metadata migration arguments."""
    parser = argparse.ArgumentParser(
        description="Validate or migrate preview metadata without running Blender."
    )
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=DEFAULT_METADATA_DIR,
        help=f"Preview JSON directory (default: {DEFAULT_METADATA_DIR}).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate without writing files.")
    mode.add_argument("--write", action="store_true", help="Atomically rewrite legacy files.")
    args = parser.parse_args()
    args.metadata_dir = args.metadata_dir.resolve()
    return args


def read_object(path: Path) -> dict[str, Any]:
    """Read one JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Metadata must be a JSON object: {path}")
    return value


def write_object_atomic(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace one JSON object."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(value, temporary_file, indent=2)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    """Validate all metadata, then optionally migrate every legacy file."""
    args = parse_args()
    paths = sorted(args.metadata_dir.glob("*.json"))
    if not paths:
        raise SystemExit(f"No JSON metadata found in {args.metadata_dir}")

    migrated: list[tuple[Path, dict[str, Any]]] = []
    skipped_count = 0
    errors: list[str] = []
    for path in paths:
        try:
            value, changed = migrate_metadata(read_object(path))
            if changed:
                migrated.append((path, value))
            else:
                skipped_count += 1
        except (OSError, ValueError) as error:
            errors.append(f"{path.name}: {error}")

    if errors:
        print("Metadata validation failed:")
        for error in errors:
            print(f"  {error}")
        raise SystemExit(1)

    if args.write:
        for path, value in migrated:
            write_object_atomic(path, value)

    action = "Migrated" if args.write else "Would migrate"
    print(f"{action} {len(migrated)} files; {skipped_count} already current")


if __name__ == "__main__":
    main()
