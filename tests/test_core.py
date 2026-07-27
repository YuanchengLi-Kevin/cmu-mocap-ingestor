# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for shared file and JSON utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core import json_io
from core.files import sha256_file


def test_sha256_file_reads_large_files_in_chunks(tmp_path: Path) -> None:
    """The file digest matches hashlib for content larger than one chunk."""
    content = b"a" * (1024 * 1024 + 17)
    path = tmp_path / "large.bin"
    path.write_bytes(content)

    assert sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_read_json_object_array_accepts_utf8_bom(tmp_path: Path) -> None:
    """Manifest reads accept the BOM emitted by some Windows tools."""
    path = tmp_path / "manifest.json"
    path.write_text('\ufeff[{"id": 1}]', encoding="utf-8")

    assert json_io.read_json_object_array(path) == [{"id": 1}]


@pytest.mark.parametrize("value", [{"id": 1}, [1], ["record"]])
def test_read_json_object_array_rejects_invalid_shapes(tmp_path: Path, value: object) -> None:
    """Manifest roots must be arrays containing only objects."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError):
        json_io.read_json_object_array(path)


def test_read_json_object_array_wraps_decode_errors(tmp_path: Path) -> None:
    """Invalid JSON reports the source path through the public ValueError API."""
    path = tmp_path / "broken.json"
    path.write_text("[", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON.*broken.json"):
        json_io.read_json_object_array(path)


def test_json_writers_emit_deterministic_indented_output(tmp_path: Path) -> None:
    """Regular and atomic writers produce the documented JSON representation."""
    records = [{"name": "café", "value": 1}]
    regular = tmp_path / "nested" / "regular.json"
    atomic = tmp_path / "nested" / "atomic.json"

    json_io.write_json_array(regular, records)
    json_io.write_json_array_atomic(atomic, records)

    expected = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    assert regular.read_text(encoding="utf-8") == expected
    assert atomic.read_text(encoding="utf-8") == expected


def test_atomic_writer_preserves_destination_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed replacement leaves the previous manifest and no temporary file."""
    path = tmp_path / "manifest.json"
    path.write_text("old\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"cannot replace {source} with {destination}")

    monkeypatch.setattr(json_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="cannot replace"):
        json_io.write_json_array_atomic(path, [{"id": 1}])

    assert path.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".manifest.json.*.tmp")) == []
