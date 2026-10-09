# Model artifacts

`current/` is created by the offline training command. FastAPI loads fixed artifact
names from this directory after validating their SHA-256 hashes against
`metadata.json`. API requests cannot choose arbitrary pickle/joblib paths.

Only load artifacts produced in this repository or received through a trusted release
channel. Joblib is not a safe format for untrusted files.

