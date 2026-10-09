# Raw authentic data

Place source files here without editing them. Record the source URL, retrieval date,
licence or access conditions, station identifiers, units and contact/request details.

The training pipeline does not guess source columns or units. Standardise a CSV with:

```powershell
Set-Location .\hydropolink-backend
python -m hydrolink_ml ingest ..\data\raw\SOURCE.csv ..\data\processed\canonical.csv `
  --source "DWS verified station export; URL and retrieval date" `
  --station-column Station --timestamp-column DateTime --value-column StageMetres
```

The input water-level values must already be in metres. Invalid timestamps are
reported rather than silently discarded, duplicates retain the most recently received
record, and missing values remain missing (they are not imputed as observations).

At the time of the first development run, no usable historical DWS/SAWS time series
had been committed. DWS verified data are available through its query-limited legacy
Hydrological Services pages. SAWS archived rainfall generally requires a formal data
request and is subject to the SAWS data policy.

