# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for the complete transactional PostgreSQL catalog import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Self

import pytest

from features import postgres


def motion_record() -> dict[str, object]:
    """Return one valid joined motion record."""
    return {
        "source_id": "cmu:01:01",
        "subject_id": 1,
        "trial_id": 1,
        "filename": "01_01.bvh",
        "subject_description": "playground",
        "description": "forward jumps",
        "frame_count": 438,
        "frame_time": 0.008333,
        "frame_rate": 120.0048,
        "duration_seconds": 3.649854,
        "joint_count": 31,
        "channel_count": 96,
        "sha256": "a" * 64,
        "validation_status": "valid",
        "relative_path": "001/01_01.bvh",
    }


def asset_record() -> dict[str, object]:
    """Return one verified motion-asset record."""
    return {
        "source_id": "cmu:01:01",
        "source_sha256": "a" * 64,
        "conversion_version": "xbot-retarget-v1",
        "playback_glb_object_key": "cmu/previews/cmu_01_01.glb",
        "playback_glb_sha256": "b" * 64,
        "playback_glb_size_bytes": 10,
        "preview_glb_object_key": "cmu/previews/cmu_01_01_in_place.glb",
        "preview_glb_sha256": "c" * 64,
        "preview_glb_size_bytes": 9,
        "preview_floor_y": 0.0,
        "preview_ceiling_y": 1.8,
        "uploaded_at": "2026-07-27T17:51:54Z",
    }


def shared_asset_record() -> dict[str, object]:
    """Return one verified shared-asset record."""
    return {
        "asset_id": "humanoid",
        "object_key": "cmu/humanoid/cmu_humanoid.glb",
        "sha256": "d" * 64,
        "size_bytes": 151240,
        "uploaded_at": "2026-07-27T17:51:54Z",
    }


def write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    """Write a JSON manifest."""
    path.write_text(json.dumps(records), encoding="utf-8")


def catalog_paths(
    tmp_path: Path,
    *,
    motion: dict[str, object] | None = None,
    asset: dict[str, object] | None = None,
    shared: dict[str, object] | None = None,
) -> tuple[Path, Path, Path]:
    """Write a complete three-manifest catalog."""
    paths = (
        tmp_path / "motions.json",
        tmp_path / "r2_assets.json",
        tmp_path / "r2_shared_assets.json",
    )
    write_manifest(paths[0], [motion or motion_record()])
    write_manifest(paths[1], [asset or asset_record()])
    write_manifest(paths[2], [shared or shared_asset_record()])
    return paths


class FakeCursor:
    """Capture table creation and ordered upsert calls."""

    def __init__(self, fail_call: int | None = None) -> None:
        self.fail_call = fail_call
        self.executed: list[str] = []
        self.upserts: list[tuple[str, list[tuple[Any, ...]]]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.executed.append(statement)

    def executemany(self, statement: str, rows: list[tuple[Any, ...]]) -> None:
        self.upserts.append((statement, rows))
        if self.fail_call == len(self.upserts):
            raise RuntimeError("database failure")


class FakeConnection:
    """Record transaction outcomes for one catalog import."""

    def __init__(self, fail_call: int | None = None) -> None:
        self.fake_cursor = FakeCursor(fail_call)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_import_catalog_creates_and_upserts_all_three_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """All catalog records commit together with values in SQL field order."""
    paths = catalog_paths(tmp_path)
    connection = FakeConnection()
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _: connection)

    counts = postgres.import_catalog("postgresql://example", *paths)

    assert counts == (1, 1, 1)
    assert len(connection.fake_cursor.executed) == 3
    assert "public.shared_assets" in connection.fake_cursor.executed[2]
    assert len(connection.fake_cursor.upserts) == 3
    assert connection.fake_cursor.upserts[2][1][0][0] == "humanoid"
    assert connection.fake_cursor.upserts[2][1][0][3] == 151240
    assert connection.committed
    assert not connection.rolled_back
    assert connection.closed


@pytest.mark.parametrize("fail_call", [1, 2, 3])
def test_import_catalog_rolls_back_failure_from_any_upsert(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fail_call: int,
) -> None:
    """A failure in any table prevents the entire catalog transaction."""
    paths = catalog_paths(tmp_path)
    connection = FakeConnection(fail_call)
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _: connection)

    with pytest.raises(RuntimeError, match="database failure"):
        postgres.import_catalog("postgresql://example", *paths)

    assert connection.rolled_back
    assert not connection.committed
    assert connection.closed


def test_catalog_validation_finishes_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid source integrity is rejected without opening PostgreSQL."""
    asset = asset_record()
    asset["source_sha256"] = "e" * 64
    paths = catalog_paths(tmp_path, asset=asset)
    monkeypatch.setattr(
        postgres.psycopg,
        "connect",
        lambda _: pytest.fail("validation should precede connection"),
    )

    with pytest.raises(ValueError, match="source SHA-256"):
        postgres.import_catalog("postgresql://example", *paths)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sha256", "UPPER", "invalid sha256"),
        ("size_bytes", 0, "invalid size_bytes"),
        ("uploaded_at", "2026-07-27", "invalid uploaded_at"),
    ],
)
def test_shared_asset_validation_rejects_invalid_integrity_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    """Shared asset digests, sizes, and timestamps use strict manifest types."""
    shared = shared_asset_record()
    shared[field] = value
    paths = catalog_paths(tmp_path, shared=shared)

    with pytest.raises(ValueError, match=message):
        postgres.import_catalog("postgresql://example", *paths)


def test_shared_asset_key_cannot_collide_with_motion_asset(tmp_path: Path) -> None:
    """Object keys remain globally unambiguous across both asset manifests."""
    shared = shared_asset_record()
    shared["object_key"] = asset_record()["playback_glb_object_key"]
    paths = catalog_paths(tmp_path, shared=shared)

    with pytest.raises(ValueError, match="across asset manifests"):
        postgres.import_catalog("postgresql://example", *paths)


def test_motion_asset_rejects_nonfinite_preview_bounds(tmp_path: Path) -> None:
    """Preview framing cannot persist NaN or infinite numeric values."""
    asset = asset_record()
    asset["preview_ceiling_y"] = float("nan")
    paths = catalog_paths(tmp_path, asset=asset)

    with pytest.raises(ValueError, match="preview_ceiling_y"):
        postgres.import_catalog("postgresql://example", *paths)
