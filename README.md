# CMU MoCap Ingestor

Ingestion and asset-conversion pipeline for the CGSpeed CMU BVH motion
dataset. It parses catalog metadata, validates BVH files, builds a joined
motion manifest, retargets animations onto a shared humanoid rig, uploads
browser-ready GLBs to Cloudflare R2, and imports verified metadata into
PostgreSQL.

## Repository layout

```text
src/core/                         Shared file and JSON helpers
src/features/
  motion_index/                   Parse the CMU catalog
  bvh_metadata/                   Validate BVHs and extract metadata
  motion_manifest/                Join catalog and BVH records
  blender_conversion/             Retarget and export animation GLBs
  skeleton_preview/               Static Three.js GLB viewer
  r2_upload/                      Upload and verify converted GLBs
  postgres/                       Import verified catalog metadata

data/manifests/                   Generated JSON manifests
data/assets/
  templates/                      Blender scene and canonical humanoid GLB
  humanoid/                       Legacy, noncanonical humanoid copy
  previews/                       Converted GLBs and preview metadata
```

Feature packages may import their own modules and shared `core` utilities,
but must not import other feature packages.

## Pipeline

```text
CMU index text ──────────────> motion_index.json
CMU BVH files ───────────────> bvh_metadata.json
motion_index + BVH metadata ─> motions.json
motions + Blender template ──> playback GLB + in-place GLB + preview JSON
converted assets ────────────> Cloudflare R2 + r2_assets.json
verified manifests ──────────> PostgreSQL
                                  public.motions
                                  public.motion_assets
                                  public.shared_assets
```

The joined manifest is BVH-led: a BVH without a catalog entry remains in
`motions.json` with a derived source ID and null descriptions.

## Setup

Python 3.12 or newer is required. From the repository root:

```powershell
python -m pip install -e ".[dev]"
```

Blender conversion additionally requires:

- Blender with BVH and glTF import/export support
- A prepared target-rig `.blend` file
- The Rokoko retargeting add-on
- `gltfpack` on `PATH`, or an explicit `--gltfpack-path`

Operational credentials belong in an ignored `.env` file. Copy the variable
names from [.env.example](.env.example).

## Generate manifests

Run the manifest stages in order:

```powershell
python -m features.motion_index
python -m features.bvh_metadata
python -m features.motion_manifest
```

Default outputs:

```text
data/manifests/motion_index.json
data/manifests/bvh_metadata.json
data/manifests/motions.json
```

`bvh_metadata` checks hierarchy declarations, channel counts, motion row
widths and values, frame counts, and frame timing. Invalid BVHs remain visible
in the manifest with `validation_status: "invalid"`.

## Convert animations

The converter retargets CMU animation onto the X Bot skeleton, retimes it to
30 FPS, and exports animation-only GLBs compatible with the canonical humanoid:

```text
data/assets/templates/cmu_humanoid.glb
```

Each successful motion produces:

```text
cmu_01_01.glb             Playback with normal root motion
cmu_01_01_in_place.glb    Preview-card animation with horizontal motion removed
cmu_01_01.json            Source fingerprint and asset integrity metadata
```

### One motion

```powershell
blender --background data\assets\templates\xbot_template.blend `
  --python src\features\blender_conversion\blender_single.py -- `
  --input data\source\cmu-mocap\data\001\01_01.bvh `
  --glb data\assets\previews\cmu_01_01.glb `
  --in-place-glb data\assets\previews\cmu_01_01_in_place.glb `
  --metadata data\assets\previews\cmu_01_01.json
```

Providing both GLB paths selects the default `both` variant.

### Batch in one Blender process

```powershell
blender --background data\assets\templates\xbot_template.blend `
  --python src\features\blender_conversion\blender_batch.py -- `
  --limit 10
```

### Isolated workers

```powershell
python -m features.blender_conversion.blender_multi_batch `
  --template-blend data\assets\templates\xbot_template.blend `
  --workers 2 `
  --limit 10
```

Resume a larger run without repeating successful conversions:

```powershell
python -m features.blender_conversion.blender_multi_batch `
  --template-blend data\assets\templates\xbot_template.blend `
  --workers 2 `
  --limit 10000 `
  --skip-existing-metadata
```

Conversion runs `gltfpack` by default with the active conversion profile.
`--no-gltfpack` is intended for debugging raw Blender exports.

## Preview locally

Start a static server:

```powershell
python -m http.server 8000
```

Open:

```text
http://localhost:8000/src/features/skeleton_preview/glb_skeleton_viewer.html
```

The viewer loads animation GLBs from `data/assets/previews/` and applies their
clips to `/data/assets/templates/cmu_humanoid.glb`.

## Upload motion assets to R2

Configure the R2 variables from `.env.example`, then upload every converted
motion:

```powershell
python -m features.r2_upload
```

The uploader validates source hashes, local GLB hashes and sizes, and unique
object keys before contacting R2. It uploads both GLB roles, verifies them with
`HEAD`, and atomically writes:

```text
data/manifests/r2_assets.json
```

For a limited trial, use a non-default output so the authoritative snapshot
cannot be replaced:

```powershell
python -m features.r2_upload `
  --limit 1 `
  --output data\manifests\r2_assets_trial.json
```

If upload or verification fails, the destination manifest remains unchanged.
Objects uploaded earlier in that attempt may remain in R2 and are safe to
overwrite because keys are deterministic.

The canonical shared humanoid is separately stored at:

```text
cmu/humanoid/cmu_humanoid.glb
```

Its verified record is in `data/manifests/r2_shared_assets.json`.

## Import PostgreSQL catalog

Set `DATABASE_URL` in `.env`, then import all three verified manifests:

```powershell
python -m features.postgres
```

Override inputs when needed:

```powershell
python -m features.postgres `
  --input data\manifests\motions.json `
  --assets-input data\manifests\r2_assets.json `
  --shared-assets-input data\manifests\r2_shared_assets.json
```

The importer validates every manifest before connecting, then creates and
upserts `public.motions`, `public.motion_assets`, and `public.shared_assets` in
one transaction. Any SQL failure rolls back the entire import.

## Data contracts

Exact JSON shapes, integrity relationships, upload guarantees, database
mappings, and preview-metadata migration commands live in
[docs/data-contracts.md](docs/data-contracts.md).

Key rules:

- `source_id` joins motion records to converted assets.
- `source_sha256` prevents uploads built from stale BVHs.
- Playback and in-place GLBs have distinct deterministic object keys.
- A `motion_assets` row means both GLB roles were uploaded and verified.
- The canonical humanoid is 151,240 bytes with SHA-256
  `492653b9e4f06f89f95050698e41f63fc86cd5ccdcc00d4dad16bf338f9354cb`.

## Contributing

Run the isolated test suite and linter:

```powershell
python -m pytest -q
python -m ruff check .
```

Tests require no Blender executable, network access, R2 credentials, or live
PostgreSQL database.
