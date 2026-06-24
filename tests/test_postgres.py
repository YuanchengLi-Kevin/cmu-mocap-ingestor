# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for PostgreSQL manifest imports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from features import postgres


def motion_record() -> dict[str, object]:
    """Return one complete joined-manifest record."""
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


class FakeCursor:
    """Minimal cursor that captures statements for unit tests."""

    def __init__(self, fail_upsert: bool = False) -> None:
        self.fail_upsert = fail_upsert
        self.executed: list[str] = []
        self.upsert_sql = ""
        self.rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.executed.append(statement)

    def executemany(self, statement: str, rows: list[tuple[Any, ...]]) -> None:
        if self.fail_upsert:
            raise RuntimeError("database failure")
        self.upsert_sql = statement
        self.rows = rows


class FakeConnection:
    """Minimal connection that records transaction handling."""

    def __init__(self, fail_upsert: bool = False) -> None:
        self.fake_cursor = FakeCursor(fail_upsert)
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


def write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    """Write test records as a JSON array."""
    path.write_text(json.dumps(records), encoding="utf-8")


def test_import_creates_table_and_upserts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A successful import creates, upserts, commits, and closes."""
    path = tmp_path / "motions.json"
    write_manifest(path, [motion_record()])
    connection = FakeConnection()
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _: connection)

    count = postgres.import_motion_manifest("postgresql://example", path)

    assert count == 1
    assert "CREATE TABLE IF NOT EXISTS" in connection.fake_cursor.executed[0]
    assert "ON CONFLICT (source_id) DO UPDATE" in connection.fake_cursor.upsert_sql
    assert len(connection.fake_cursor.rows) == 1
    assert connection.committed
    assert not connection.rolled_back
    assert connection.closed


def test_import_rolls_back_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Any SQL failure rolls back and closes the connection."""
    path = tmp_path / "motions.json"
    write_manifest(path, [motion_record()])
    connection = FakeConnection(fail_upsert=True)
    monkeypatch.setattr(postgres.psycopg, "connect", lambda _: connection)

    with pytest.raises(RuntimeError, match="database failure"):
        postgres.import_motion_manifest("postgresql://example", path)

    assert connection.rolled_back
    assert not connection.committed
    assert connection.closed


def test_import_rejects_invalid_status(tmp_path: Path) -> None:
    """Invalid validation states fail before opening a database connection."""
    path = tmp_path / "motions.json"
    record = motion_record()
    record["validation_status"] = "unknown"
    write_manifest(path, [record])

    with pytest.raises(ValueError, match="validation_status"):
        postgres.import_motion_manifest("postgresql://example", path)
