# CMU MoCap Ingestor

Ingestion and asset-conversion pipeline for the CGSpeed CMU BVH motion dataset.
The project parses catalog metadata, validates BVH files, builds a joined motion
manifest, retargets animations onto a shared humanoid rig, and exports
browser-ready GLBs with integrity metadata.

The PostgreSQL feature imports the joined motion manifest and verified R2 asset
metadata. The R2 upload feature uploads and verifies converted GLBs and writes
the authoritative asset manifest.

## Repository layout

```text
src/core/
  files.py
  json_io.py

src/features/
  motion_index/          Parse CMU catalog descriptions
  bvh_metadata/          Validate BVHs and extract source metadata
  motion_manifest/       Join catalog and BVH metadata
  blender_conversion/    Retarget, export, and describe GLB assets
  skeleton_preview/      Static Three.js GLB viewer
  r2_upload/              Upload and verify converted GLBs in Cloudflare R2
  postgres/              Import motions and verified assets into PostgreSQL

data/manifests/
  source.json
  motion_index.json
  bvh_metadata.json
  motions.json

data/assets/
  templates/             Prepared Blender target-rig scene
  humanoid/              Shared browser humanoid asset
  previews/              Normal GLBs, in-place GLBs, and preview JSON
```

Feature packages may import their own internal modules and shared `core`
utilities, but must not import other feature packages.

## Pipeline

```text
CMU index text
    -> features.motion_index
    -> data/manifests/motion_index.json

CMU BVH files
    -> features.bvh_metadata
    -> data/manifests/bvh_metadata.json

motion_index.json + bvh_metadata.json
    -> features.motion_manifest
    -> data/manifests/motions.json

motions.json + prepared Blender template
    -> features.blender_conversion
    -> normal playback GLB
    -> in-place preview-card GLB
    -> schema-v2 preview JSON

motions.json
    -> features.postgres
    -> public.motions

motions.json + converted GLBs + preview JSON
    -> features.r2_upload
    -> Cloudflare R2 + data/manifests/r2_assets.json

motions.json + r2_assets.json
    -> features.postgres
    -> public.motions + public.motion_assets
```

The joined manifest is BVH-led. A BVH without a motion-index entry remains in
`motions.json` with a derived `source_id` and null descriptions.

## Setup

Run commands from the repository root with the virtual environment activated:

```powershell
python -m pip install -e ".[dev]"
```

Blender conversion also requires:

- Blender with BVH and glTF import/export support
- a prepared target-rig `.blend` file
- the Rokoko retargeting add-on available to Blender
- `gltfpack` on `PATH`, or an explicit `--gltfpack-path`

## Generate manifests

Run the three manifest stages in order:

```powershell
python -m features.motion_index
python -m features.bvh_metadata
python -m features.motion_manifest
```

Default outputs are:

```text
data/manifests/motion_index.json
data/manifests/bvh_metadata.json
data/manifests/motions.json
```

`bvh_metadata` validates hierarchy declarations, motion row sizes, numeric
values, frame counts, and frame timing. It also records the original BVH
SHA-256 and `source_size_bytes`.

## Blender conversion

The converter imports a CMU BVH, retargets it onto the X Bot skeleton, retimes
the animation, and exports animation-only GLBs that target the same Mixamo bone
names as the shared humanoid.

Each successfully converted motion produces two GLBs by default:

```text
data/assets/previews/cmu_01_01.glb
  Normal root motion; loaded after the user selects a motion.

data/assets/previews/cmu_01_01_in_place.glb
  Horizontal root motion removed; used for an animated preview card.

data/assets/previews/cmu_01_01.json
  Source fingerprint, export timing, GLB hashes, sizes, object keys, and framing.
```

The website should expose one searchable motion, not two searchable variants.
The normal and in-place GLBs are assets with playback and preview-card roles.

CMU source timing is approximately 120 FPS. The current conversion profile
retimes exports to 30 FPS and trims one exported frame from the start.

### Convert one motion

Run Blender with a template that already contains the prepared target rig:

```powershell
blender --background data\assets\templates\xbot_template.blend --python src\features\blender_conversion\blender_single.py -- --input data\source\cmu-mocap\data\001\01_01.bvh --glb data\assets\previews\cmu_01_01.glb --in-place-glb data\assets\previews\cmu_01_01_in_place.glb --metadata data\assets\previews\cmu_01_01.json
```

Providing both output paths makes the default variant `both`.

### Convert a batch in one Blender process

This processes the first 10 valid manifest records and produces both GLBs for
each motion:

```powershell
blender --background data\assets\templates\xbot_template.blend --python src\features\blender_conversion\blender_batch.py -- --limit 10
```

### Convert with isolated workers

The multi-worker launcher shards records across independent headless Blender
processes:

```powershell
python -m features.blender_conversion.blender_multi_batch --template-blend data\assets\templates\xbot_template.blend --workers 2 --limit 10
```

To resume a larger run without reconverting records whose JSON metadata is
already marked `converted`:

```powershell
python -m features.blender_conversion.blender_multi_batch --template-blend data\assets\templates\xbot_template.blend --workers 2 --limit 10000 --skip-existing-metadata
```

The limit is applied after existing converted records are skipped.

### GLB optimization

Conversion runs `gltfpack` by default with the arguments defined by the active
conversion profile. Use `--gltfpack-path` when the executable is not on `PATH`.
`--no-gltfpack` is intended only for debugging raw Blender exports.

## Conversion profiles and preview metadata

Shared conversion settings live in
`src/features/blender_conversion/conversion_profiles.json`, keyed by
`conversion_version`. Per-motion JSON stores only the source fingerprint and
values specific to that conversion and its generated assets.

Current preview metadata uses `metadata_schema_version: 2`:

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

`source_sha256` intentionally overlaps with the source manifest so stale GLBs
can be detected. Shared rig, axis, trimming, and optimization settings belong to
the conversion profile instead of every per-motion JSON file.

### Migrate legacy preview JSON

This is a local JSON schema migration. It does not connect to PostgreSQL, run
Blender, modify GLBs, or upload to R2.

Validate every JSON before writing:

```powershell
python -m features.blender_conversion.migrate_metadata --dry-run
```

Atomically rewrite legacy JSON after validation succeeds:

```powershell
python -m features.blender_conversion.migrate_metadata --write
```

Already migrated schema-v2 files are validated and skipped.

## Skeleton preview

Run a local static server from the repository root:

```powershell
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/src/features/skeleton_preview/glb_skeleton_viewer.html
```

The viewer loads repository-relative paths such as:

```text
/data/assets/previews/cmu_01_01.glb
/data/assets/humanoid/cmu_humanoid.glb
```

The browser loads the shared humanoid once, then applies animation clips from
the animation-only GLBs to its matching Mixamo skeleton.

## Cloudflare R2 upload

Create R2 S3 API credentials and add the upload configuration to `.env`:

```dotenv
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET_NAME=your-bucket
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key
```

Upload every converted motion and atomically write the verified full-snapshot
asset manifest:

```powershell
python -m features.r2_upload
```

The feature validates all selected source hashes, local GLB hashes, sizes, and
object-key uniqueness before contacting R2. It uploads both GLB roles, verifies
their sizes and recorded SHA-256 metadata with R2 `HEAD` requests, and writes:

```text
data/manifests/r2_assets.json
```

For a limited trial, use a non-default output so the full manifest cannot be
replaced accidentally:

```powershell
python -m features.r2_upload --limit 1 --output data\manifests\r2_assets_trial.json
```

If an upload or verification fails, the destination manifest is left unchanged.
Objects uploaded earlier in that attempt may remain in R2 and can be overwritten
safely by a retry because object keys are deterministic.

## PostgreSQL import

Create a `.env` file containing:

```dotenv
DATABASE_URL=postgresql://username:password@localhost:5432/database_name
```

Then import both catalog manifests:

```powershell
python -m features.postgres
```

The importer creates `public.motions` and `public.motion_assets` when necessary,
then atomically upserts records from `data/manifests/motions.json` and verified
asset records from `data/manifests/r2_assets.json` by `source_id`.

Override either input when needed:

```powershell
python -m features.postgres `
  --input data\manifests\motions.json `
  --assets-input data\manifests\r2_assets.json
```

Before opening PostgreSQL, the importer verifies asset source IDs and source
hashes against the motion manifest, requires valid BVHs, validates both GLB
roles and their integrity metadata, checks object-key uniqueness, and validates
upload timestamps. Local preview JSON and failed conversions are not imported;
a `public.motion_assets` row means both GLBs were uploaded and verified.

## Manifest schemas

### Motion index

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

### BVH metadata

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

### Joined motion manifest

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

`source_size_bytes` is currently generated in `bvh_metadata.json` but is not yet
propagated into `motions.json` or PostgreSQL.

## R2 asset flow

The preview JSON contains deterministic object keys, hashes, and sizes. Verified
uploads flow into PostgreSQL as:

```text
validated converted GLBs
    -> upload normal and in-place GLBs to Cloudflare R2
    -> verify both objects
    -> generate a successful-assets manifest
    -> import one motion_assets row per source_id into PostgreSQL
```

The catalog searches one `motions` row per animation and joins its corresponding
`motion_assets` row. The preview card uses the in-place GLB object key, while
the detail viewer uses the normal GLB object key.
