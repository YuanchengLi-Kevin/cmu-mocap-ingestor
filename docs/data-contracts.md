# Data Contracts

This reference documents the generated JSON exchanged by the CMU MoCap
pipeline. Manifests under `data/manifests/` and converted assets under
`data/assets/` are generated data and are ignored by Git.

## Data flow

```text
motion_index.json + bvh_metadata.json
    -> motions.json

motions.json + converted preview metadata
    -> verified R2 uploads
    -> r2_assets.json

motions.json + r2_assets.json + r2_shared_assets.json
    -> public.motions
    -> public.motion_assets
    -> public.shared_assets
```

## Motion index

`features.motion_index` parses the CMU catalog into
`data/manifests/motion_index.json`:

```json
{
  "source_id": "cmu:01:01",
  "subject_id": 1,
  "trial_id": 1,
  "filename": "01_01.bvh",
  "subject_description": "climb, swing, hang on playground equipment",
  "description": "playground - forward jumps, turn around"
}
```

`source_id`, subject, and trial identifiers are derived from the catalog
animation name. An animation before a subject heading or under a conflicting
subject heading is rejected.

## BVH metadata

`features.bvh_metadata` recursively validates source BVHs and writes
`data/manifests/bvh_metadata.json`:

```json
{
  "filename": "01_01.bvh",
  "relative_path": "001/01_01.bvh",
  "subject_id": 1,
  "trial_id": 1,
  "source_size_bytes": 12345678,
  "sha256": "abc123...",
  "frame_count": 2752,
  "frame_time": 0.0083333,
  "frame_rate": 120.00048,
  "duration_seconds": 22.9332416,
  "joint_count": 31,
  "channel_count": 96,
  "validation_status": "valid"
}
```

Validation covers:

- Expected `subject_trial.bvh` filenames
- `HIERARCHY`, `ROOT`, `JOINT`, `CHANNELS`, and `MOTION` declarations
- Declared frame count versus motion row count
- Motion row channel widths and numeric values
- Positive frame timing
- Duplicate filenames across the recursive input tree

Invalid BVHs remain in the manifest with `validation_status: "invalid"`.

## Joined motions

`features.motion_manifest` performs a BVH-left join and atomically writes
`data/manifests/motions.json`:

```json
{
  "source_id": "cmu:01:01",
  "subject_id": 1,
  "trial_id": 1,
  "filename": "01_01.bvh",
  "subject_description": "climb, swing, hang on playground equipment",
  "description": "playground - forward jumps, turn around",
  "frame_count": 2752,
  "frame_time": 0.0083333,
  "frame_rate": 120.00048,
  "duration_seconds": 22.9332416,
  "joint_count": 31,
  "channel_count": 96,
  "sha256": "abc123...",
  "validation_status": "valid",
  "relative_path": "001/01_01.bvh"
}
```

A BVH without a motion-index match is retained with a derived `source_id` and
null descriptions. An index-only record is counted but omitted. Duplicate
filenames, source IDs, missing fields, and conflicting identities are rejected.

`source_size_bytes` is generated in `bvh_metadata.json` but is not currently
propagated into `motions.json` or PostgreSQL.

## Conversion metadata schema v2

Each successful Blender conversion writes one preview metadata object beside
its two GLBs:

```json
{
  "metadata_schema_version": 2,
  "source_id": "cmu:01:01",
  "conversion_status": "converted",
  "conversion_version": "xbot-retarget-v1",
  "error_message": null,
  "source_sha256": "abc123...",
  "source_frame_start": 1,
  "source_frame_end": 2752,
  "export_frame_start": 2,
  "export_frame_end": 689,
  "export_frame_count": 688,
  "export_frame_rate": 30.0,
  "export_duration_seconds": 22.9333333333,
  "variants": {
    "normal": {
      "glb_relative_path": "data/assets/previews/cmu_01_01.glb",
      "glb_object_key": "cmu/previews/cmu_01_01.glb",
      "glb_sha256": "def456...",
      "glb_size_bytes": 65680
    },
    "in_place": {
      "glb_relative_path": "data/assets/previews/cmu_01_01_in_place.glb",
      "glb_object_key": "cmu/previews/cmu_01_01_in_place.glb",
      "glb_sha256": "789abc...",
      "glb_size_bytes": 64160,
      "in_place_neutralized_location_curves": 2,
      "preview_frame": {
        "floor_y": 0.0,
        "ceiling_y": 0.7793633461
      }
    }
  }
}
```

`source_sha256` binds the conversion to its source BVH. Shared rig, axis,
trimming, timing, and optimization settings live in
`conversion_profiles.json`, keyed by `conversion_version`.

Failed conversions contain identity, status, version, error, and source hash,
but no verified variants.

## Verified motion assets

After both GLB roles pass R2 `HEAD` verification,
`features.r2_upload` writes one record to `data/manifests/r2_assets.json`:

```json
{
  "source_id": "cmu:01:01",
  "source_sha256": "abc123...",
  "conversion_version": "xbot-retarget-v1",
  "playback_glb_object_key": "cmu/previews/cmu_01_01.glb",
  "playback_glb_sha256": "def456...",
  "playback_glb_size_bytes": 65680,
  "preview_glb_object_key": "cmu/previews/cmu_01_01_in_place.glb",
  "preview_glb_sha256": "789abc...",
  "preview_glb_size_bytes": 64160,
  "preview_floor_y": 0.0,
  "preview_ceiling_y": 0.7793633461,
  "uploaded_at": "2026-07-27T00:00:00Z"
}
```

The uploader validates all selected records before contacting R2:

- The motion exists and is valid.
- The conversion uses metadata schema v2.
- The source hash matches `motions.json`.
- Both local GLBs match their recorded hashes and sizes.
- Local paths remain inside the repository.
- Object keys are nonempty and unique.

Uploaded objects use `model/gltf-binary` and record source, role, conversion,
and GLB hash metadata. A `HEAD` response must match the expected size and
`glb_sha256`. The manifest is atomically replaced only after every selected
pair succeeds.

## Shared assets

The canonical humanoid source is:

```text
data/assets/templates/cmu_humanoid.glb
```

It is stored in R2 at `cmu/humanoid/cmu_humanoid.glb` and recorded in
`data/manifests/r2_shared_assets.json`:

```json
{
  "asset_id": "humanoid",
  "object_key": "cmu/humanoid/cmu_humanoid.glb",
  "sha256": "492653b9e4f06f89f95050698e41f63fc86cd5ccdcc00d4dad16bf338f9354cb",
  "size_bytes": 151240,
  "uploaded_at": "2026-07-27T21:23:50.067752Z"
}
```

The older file under `data/assets/humanoid/` is a noncanonical local copy.

## PostgreSQL mapping

`features.postgres` validates all three input manifests before connecting:

- `public.motions` is keyed by `source_id`.
- `public.motion_assets` is keyed by and references `motions.source_id`.
- `public.shared_assets` is keyed by `asset_id`.
- Motion assets must reference valid motions with matching source hashes.
- Digests must be lowercase SHA-256 values, sizes must be positive integers,
  preview bounds must be finite, and upload timestamps must include a timezone.
- Object keys must be unique within motion assets and cannot collide with
  shared assets.

Table creation and all upserts run in one transaction. Any SQL error rolls back
the complete catalog import. `updated_at` is managed by PostgreSQL and refreshed
on conflict updates.

## Migrate legacy preview metadata

The migration validates local JSON only. It does not run Blender, modify GLBs,
connect to PostgreSQL, or upload to R2.

Validate every preview metadata file before writing:

```powershell
python -m features.blender_conversion.migrate_metadata --dry-run
```

Atomically rewrite legacy records after all files validate:

```powershell
python -m features.blender_conversion.migrate_metadata --write
```

Already-current schema-v2 records are validated and skipped. An unsupported
schema version or legacy record that disagrees with its conversion profile
stops the migration before any file is rewritten.
