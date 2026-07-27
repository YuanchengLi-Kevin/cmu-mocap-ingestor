# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for public command-line orchestration contracts."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from features.bvh_metadata import __main__ as bvh_main
from features.motion_index import __main__ as index_main
from features.motion_manifest import JoinSummary
from features.motion_manifest import __main__ as manifest_main
from features.postgres import __main__ as postgres_main
from features.r2_upload import __main__ as r2_main


def test_motion_index_main_forwards_paths_and_reports_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The index CLI forwards parsed paths to the feature API."""
    source = tmp_path / "index.txt"
    output = tmp_path / "motion_index.json"
    calls = []
    monkeypatch.setattr(index_main, "parse_args", lambda: Namespace(input=source, output=output))
    monkeypatch.setattr(
        index_main,
        "write_motion_index_manifest",
        lambda *args: calls.append(args) or 3,
    )

    index_main.main()

    assert calls == [(source, output)]
    assert "Wrote 3 animation records" in capsys.readouterr().out


def test_bvh_main_reports_total_and_valid_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The BVH CLI exposes both snapshot and validation counts."""
    source = tmp_path / "data"
    output = tmp_path / "bvh.json"
    monkeypatch.setattr(bvh_main, "parse_args", lambda: Namespace(input=source, output=output))
    monkeypatch.setattr(bvh_main, "write_bvh_metadata_manifest", lambda *args: (5, 4))

    bvh_main.main()

    output_text = capsys.readouterr().out
    assert "Wrote 5 records" in output_text
    assert "(4 valid)" in output_text


def test_motion_manifest_main_forwards_all_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The join CLI reports every category in its summary."""
    args = Namespace(
        motion_index=tmp_path / "index.json",
        bvh_metadata=tmp_path / "bvh.json",
        output=tmp_path / "motions.json",
    )
    calls = []
    monkeypatch.setattr(manifest_main, "parse_args", lambda: args)
    monkeypatch.setattr(
        manifest_main,
        "build_joined_manifest",
        lambda *values: calls.append(values) or JoinSummary(4, 2, 1, 1),
    )

    manifest_main.main()

    assert calls == [(args.motion_index, args.bvh_metadata, args.output)]
    assert "2 matched, 1 BVH-only, 1 index-only omitted" in capsys.readouterr().out


def test_r2_main_rejects_limited_default_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trial upload cannot overwrite the authoritative full manifest."""
    monkeypatch.setattr(
        r2_main,
        "parse_args",
        lambda: Namespace(
            motions=r2_main.DEFAULT_MOTIONS,
            metadata_dir=r2_main.DEFAULT_METADATA_DIR,
            output=r2_main.DEFAULT_OUTPUT,
            limit=1,
        ),
    )

    with pytest.raises(SystemExit, match="--limit requires"):
        r2_main.main()


def test_r2_main_builds_client_and_forwards_prepared_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The R2 CLI wires validated inputs, credentials, client, and output together."""
    args = Namespace(
        motions=tmp_path / "motions.json",
        metadata_dir=tmp_path / "metadata",
        output=tmp_path / "trial.json",
        limit=1,
    )
    client = object()
    client_kwargs = {}
    uploaded = []
    monkeypatch.setattr(r2_main, "parse_args", lambda: args)
    monkeypatch.setattr(r2_main, "load_dotenv", lambda *args: None)
    for name, value in {
        "R2_ENDPOINT_URL": "https://r2.example",
        "R2_BUCKET_NAME": "bucket",
        "R2_ACCESS_KEY_ID": "access",
        "R2_SECRET_ACCESS_KEY": "secret",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        r2_main,
        "prepare_uploads",
        lambda *values: ["prepared"],
    )

    def fake_client(service: str, **kwargs: object) -> object:
        client_kwargs.update(service=service, **kwargs)
        return client

    monkeypatch.setattr(r2_main.boto3, "client", fake_client)
    monkeypatch.setattr(
        r2_main,
        "upload_prepared_assets",
        lambda *values: uploaded.append(values) or 1,
    )

    r2_main.main()

    assert client_kwargs["service"] == "s3"
    assert client_kwargs["region_name"] == "auto"
    assert uploaded == [(client, "bucket", ["prepared"], args.output)]
    assert "Uploaded and verified 1 motions" in capsys.readouterr().out


def test_postgres_main_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The database CLI fails before import when configuration is absent."""
    monkeypatch.setattr(postgres_main, "load_dotenv", lambda *args: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        postgres_main,
        "parse_args",
        lambda: Namespace(input=Path("a"), assets_input=Path("b"), shared_assets_input=Path("c")),
    )

    with pytest.raises(SystemExit, match="DATABASE_URL is required"):
        postgres_main.main()


def test_postgres_main_forwards_three_manifests_and_reports_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The catalog CLI includes the shared-asset manifest and singularizes counts."""
    args = Namespace(
        input=Path("motions.json"),
        assets_input=Path("assets.json"),
        shared_assets_input=Path("shared.json"),
    )
    calls = []
    monkeypatch.setattr(postgres_main, "parse_args", lambda: args)
    monkeypatch.setattr(postgres_main, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(
        postgres_main,
        "import_catalog",
        lambda *values: calls.append(values) or (2, 2, 1),
    )

    postgres_main.main()

    assert calls == [
        (
            "postgresql://example",
            args.input,
            args.assets_input,
            args.shared_assets_input,
        )
    ]
    assert "1 record into public.shared_assets" in capsys.readouterr().out
