# HydroLink data layout

- `raw/`: immutable source downloads or manually supplied authentic files.
- `processed/`: canonical, deduplicated chronological splits used by the pipeline.
- `synthetic/`: clearly labelled generated development observations and injected faults.

No file under `synthetic/` is DWS, SAWS, or municipal data. Generated files retain a
`source` field and fault labels. Authentic source files must retain their original
license/provenance alongside the file.

