# CMU MoCap Ingestor

Ingestion pipeline for the CGSpeed CMU BVH motion dataset.

The project parses CMU motion index metadata, extracts BVH file metadata, joins both
sources into a normalized manifest, and optionally imports the joined records into
PostgreSQL.

## Repository layout

```text
scripts/
  parse_motion_index.py
  parse_bvh_metadata.py
  build_manifest.py
  import_postgres.py

src/cmu_mocap_ingestor/
  motion_index.py
  bvh.py
  manifest.py
  postgres.py

data/manifests/
  source.json
  motion_index.json
  bvh_metadata.json
  motions.json
```

Scripts coordinate pipeline stages. Reusable parsing, manifest, and database logic
belongs in `src/cmu_mocap_ingestor/`.

## Pipeline stages

```text
parse_motion_index.py  -> data/manifests/motion_index.json
parse_bvh_metadata.py  -> data/manifests/bvh_metadata.json
build_manifest.py      -> data/manifests/motions.json
import_postgres.py     -> PostgreSQL rows
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
python .\scripts\parse_motion_index.py
python .\scripts\parse_bvh_metadata.py
python .\scripts\build_manifest.py
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

The current Blender/Rokoko proof-of-concept is `scripts/blender_single.py`. It:

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

Run the script from a Blender scene that already contains the posed X Bot
template, or later from headless Blender with a template `.blend`:

```powershell
blender --background xbot_template.blend --python scripts\blender_single.py
```

## Import into PostgreSQL

Create a `.env` file containing:

```dotenv
DATABASE_URL=postgresql://username:password@localhost:5432/database_name
```

Then run:

```powershell
python .\scripts\import_postgres.py
```

The importer creates `public.motions` if necessary and upserts every record by
`source_id`.

## Development pattern

Keep scripts thin. For example, `scripts/parse_bvh_metadata.py` should only
coordinate paths, call package code, and report results:

```python
from pathlib import Path

from cmu_mocap_ingestor.bvh import write_bvh_metadata_manifest


def main() -> None:
    input_directory = Path("data/source/cmu-mocap/data")
    output_path = Path("data/manifests/bvh_metadata.json")

    count, valid_count = write_bvh_metadata_manifest(
        input_root=input_directory,
        output_path=output_path,
    )

    print(f"Processed {count} BVH files ({valid_count} valid)")


if __name__ == "__main__":
    main()
```

The actual parsing belongs in `src/cmu_mocap_ingestor/bvh.py`.

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
