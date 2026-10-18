"""Versioned artifact persistence with explicit paths and integrity checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from .anomaly import AnomalyBundle
from .forecasting import ForecastBundle


ARTIFACT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class LoadedArtifacts:
    anomaly: AnomalyBundle
    forecast: ForecastBundle
    metadata: dict[str, Any]
    history_rows: list[dict[str, object]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.name in {"", ".", ".."}:
        raise ValueError("artifact directory must be explicit")
    return resolved


def save_artifacts(
    directory: Path,
    anomaly: AnomalyBundle,
    forecast: ForecastBundle,
    metadata: dict[str, Any],
    history_rows: list[dict[str, object]],
) -> dict[str, Any]:
    target = _safe_directory(directory)
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "anomaly": target / "anomaly.joblib",
        "forecast": target / "forecast.joblib",
        "history": target / "history.joblib",
    }
    joblib.dump(anomaly, files["anomaly"], compress=3)
    joblib.dump(forecast, files["forecast"], compress=3)
    joblib.dump(history_rows, files["history"], compress=3)
    manifest = dict(metadata)
    manifest.update(
        {
            "artifact_format_version": ARTIFACT_FORMAT_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "files": {
                name: {"name": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}
                for name, path in files.items()
            },
        }
    )
    manifest_path = target / "metadata.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def load_artifacts(directory: Path) -> LoadedArtifacts:
    """Load only the fixed, locally managed artifact names after hash validation.

    joblib uses pickle internally, so this function intentionally accepts no filename
    from an API request and must only point at artifacts created by the training CLI.
    """
    target = _safe_directory(directory)
    manifest_path = target / "metadata.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"model metadata not found: {manifest_path}")
    metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    if metadata.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
        raise ValueError("unsupported artifact format version")
    expected_names = {"anomaly": "anomaly.joblib", "forecast": "forecast.joblib", "history": "history.joblib"}
    paths: dict[str, Path] = {}
    for key, fixed_name in expected_names.items():
        file_metadata = metadata.get("files", {}).get(key, {})
        if file_metadata.get("name") != fixed_name:
            raise ValueError(f"unexpected artifact filename for {key}")
        path = target / fixed_name
        if not path.is_file() or _sha256(path) != file_metadata.get("sha256"):
            raise ValueError(f"artifact integrity check failed for {fixed_name}")
        paths[key] = path
    anomaly = joblib.load(paths["anomaly"])
    forecast = joblib.load(paths["forecast"])
    history = joblib.load(paths["history"])
    if not isinstance(anomaly, AnomalyBundle) or not isinstance(forecast, ForecastBundle):
        raise TypeError("artifact content has an unexpected type")
    if not isinstance(history, list):
        raise TypeError("history artifact must be a list")
    return LoadedArtifacts(anomaly=anomaly, forecast=forecast, metadata=metadata, history_rows=history)

