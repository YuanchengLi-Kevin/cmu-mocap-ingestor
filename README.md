# Project structure

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

The scripts coordinate each pipeline stage:

```text
parse_motion_index.py  -> data/manifests/motion_index.json
parse_bvh_metadata.py  -> data/manifests/bvh_metadata.json
build_manifest.py      -> data/manifests/motions.json
import_postgres.py     -> PostgreSQL rows
```

## Keep scripts thin

For example, `scripts/parse_bvh_metadata.py` should coordinate the operation:

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

The actual parsing belongs in:

`src/cmu_mocap_ingestor/bvh.py`

This separation makes the code easier to test and makes the repository look like a proper software project rather than a collection of one-off scripts.

## Run the pipeline

Run each stage from the repository root with the virtual environment activated:

```powershell
python .\scripts\parse_motion_index.py
python .\scripts\parse_bvh_metadata.py
python .\scripts\build_manifest.py
```

The joined manifest uses every BVH as its base. BVHs without motion-index entries remain in
`motions.json` with derived source IDs and null descriptions.

To import the joined manifest into PostgreSQL, create a `.env` file containing:

```dotenv
DATABASE_URL=postgresql://username:password@localhost:5432/database_name
```

Then run:

```powershell
python .\scripts\import_postgres.py
```

The importer creates `public.motions` if necessary and upserts every record by `source_id`.


## Motion Index template (one record)
```JSON
{
"source_id": "cmu:01:01",
"subject_id": 1,
"trial_id": 1,
"filename": "01_01.bvh",
"subject_description": "climb, swing, hang on playground equipment",
"description": "playground - forward jumps, turn around"
}
```
## BVH Parser template (one record)

filename
relative path
subject ID
trial ID
SHA-256
frame count
frame time
frame rate
duration
joint count
channel count
validation status

## Join motion index and BVH (one record)
```JSON
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
  "duration_seconds": 3.6499,
  "joint_count": 31,
  "channel_count": 96,
  "sha256": "abc123...",
  "validation_status": "valid",
  "relative_path": "001/01_01.bvh"
}
```
