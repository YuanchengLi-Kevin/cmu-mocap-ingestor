# CMU MoCap Ingestor

Ingestion pipeline for the CGSpeed CMU BVH motion dataset.

The project parses CMU motion index metadata, extracts BVH file metadata, joins both
sources into a normalized manifest, and optionally imports the joined records into
PostgreSQL.

## Repository layout

```text
src/core/
  files.py
  json_io.py

src/features/
  motion_index/
  bvh_metadata/
  motion_manifest/
  postgres/
  blender_conversion/
  skeleton_preview/

data/manifests/
  source.json
  motion_index.json
  bvh_metadata.json
  motions.json
```

Feature packages own one pipeline capability each. Shared utilities live in
`src/core/`. Features may import from `core`, but should not import from each
other.

## Pipeline stages

```text
python -m features.motion_index     -> data/manifests/motion_index.json
python -m features.bvh_metadata     -> data/manifests/bvh_metadata.json
python -m features.motion_manifest  -> data/manifests/motions.json
python -m features.postgres         -> PostgreSQL rows
```

The joined manifest uses every BVH as its base. BVHs without motion-index entries
remain in `motions.json` with derived source IDs and null descriptions.

## Setup

Run commands from the repository root with the virtual environment activated.

```powershell
python -m pip install -e .[dev]
```

## Run the pipeline

```powershell
python -m features.motion_index
python -m features.bvh_metadata
python -m features.motion_manifest
```

## Skeleton preview

The skeleton preview is a static Three.js viewer for exported GLB animations.
Run a local static server from the repository root:

```powershell
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/src/features/skeleton_preview/glb_skeleton_viewer.html
```

The viewer loads paths relative to the repository server. For example:

```text
/data/assets/previews/cmu_01_01.glb
/data/assets/humanoid/cmu_humanoid.glb
```

## Blender retargeting

The CMU BVH files use a consistent source skeleton across the dataset. Retargeting
can therefore use one source-to-target setup instead of solving a new rig map for
each clip.

The intended asset layout is:

```text
humanoid/xbot.glb
  Mixamo X Bot mesh and skeleton

animations/cmu_01_01.glb
animations/cmu_01_02.glb
animations/cmu_01_03.glb
  animation-only GLBs exported on the X Bot skeleton
```

The animation GLBs do not directly reference `xbot.glb`. The browser loads the X
Bot GLB once, then loads each animation GLB and applies its animation clip to the
already loaded X Bot scene. For this to work, every exported animation clip must
target the same Mixamo bone names as `xbot.glb`.

The current Blender/Rokoko proof-of-concept is
`src/features/blender_conversion/blender_single.py`. It:

```text
imports one CMU BVH
sets the BVH armature as the Rokoko source
sets the Mixamo X Bot armature as the Rokoko target
builds Rokoko's bone list
removes unsupported hand/finger/thumb mappings
retargets the motion onto X Bot
removes the source BVH object and source action
exports an armature-only GLB with one animation
```

The scene FPS is set to 120 to preserve CMU BVH timing. If this is left at
Blender's default FPS, exported animations play in slow motion.

Run the script from headless Blender with a template `.blend` that already
contains the posed X Bot target rig:

```powershell
blender --background data\assets\templates\xbot_template.blend --python src\features\blender_conversion\blender_single.py -- --input data\source\cmu-mocap\data\001\01_01.bvh --glb data\assets\previews\cmu_01_01.glb --metadata data\assets\previews\cmu_01_01.json
```

The conversion scripts optimize GLBs with `gltfpack` by default. Pass
`--gltfpack-path` when `gltfpack.exe` is not on `PATH`. Pass `--no-gltfpack`
only when debugging Blender's raw GLB export.

To process the first 10 valid BVH records in one headless Blender process:

```powershell
blender --background data\assets\templates\xbot_template.blend --python src\features\blender_conversion\blender_batch.py -- --variant both --limit 10
```

## Import into PostgreSQL

Create a `.env` file containing:

```dotenv
DATABASE_URL=postgresql://username:password@localhost:5432/database_name
```

Then run:

```powershell
python -m features.postgres
```

The importer creates `public.motions` if necessary and upserts every record by
`source_id`.

## Manifest records

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
  "sha256": "abc123...",
  "frame_count": 438,
  "frame_time": 0.008333,
  "frame_rate": 120.0048,
  "duration_seconds": 3.649854,
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
  "frame_count": 438,
  "frame_time": 0.008333,
  "frame_rate": 120.0048,
  "duration_seconds": 3.649854,
  "joint_count": 31,
  "channel_count": 96,
  "sha256": "abc123...",
  "validation_status": "valid",
  "relative_path": "001/01_01.bvh"
}
```

## Cloudflare R2 architecture notes

```text
Existing Python repository
|-- download CMU data
|-- parse catalog metadata
|-- process animation files
|-- upload files to R2
`-- insert metadata and object keys into PostgreSQL

Catalog backend
|-- query PostgreSQL
`-- return animation metadata and R2 object URL

Browser
|-- request catalog data from backend
`-- load animation file directly from R2
```
