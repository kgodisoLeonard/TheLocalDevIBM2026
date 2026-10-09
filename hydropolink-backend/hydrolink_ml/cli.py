"""Command-line entry points for data import, training, evaluation and prediction."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import ARTIFACT_ROOT
from .inference import HydroLinkInferenceService
from .ingestion import import_historical_csv
from .pipeline import evaluate_saved_pipeline, train_pipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HydroLink SA offline ML workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train", help="train, evaluate and persist model artifacts")
    train.add_argument("--input", type=Path, help="canonical authentic historical CSV; omit for synthetic development mode")
    train.add_argument("--artifacts", type=Path, default=ARTIFACT_ROOT / "current")

    evaluate = subparsers.add_parser("evaluate", help="re-evaluate persisted models on the saved held-out split")
    evaluate.add_argument("--artifacts", type=Path, default=ARTIFACT_ROOT / "current")

    ingest = subparsers.add_parser("ingest", help="standardise a mapped historical CSV")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("output", type=Path)
    ingest.add_argument("--source", required=True)
    ingest.add_argument("--station-column", default="station_id")
    ingest.add_argument("--timestamp-column", default="timestamp")
    ingest.add_argument("--value-column", default="value_m")
    ingest.add_argument("--rainfall-column")
    ingest.add_argument("--latitude-column")
    ingest.add_argument("--longitude-column")

    predict = subparsers.add_parser("predict", help="run one inference using validated saved artifacts")
    predict.add_argument("station_id")
    predict.add_argument("value_m", type=float)
    predict.add_argument("--timestamp", default=datetime.now(timezone.utc).isoformat())
    predict.add_argument("--artifacts", type=Path, default=ARTIFACT_ROOT / "current")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "train":
        output = train_pipeline(input_csv=args.input, artifact_directory=args.artifacts)
    elif args.command == "evaluate":
        output = evaluate_saved_pipeline(artifact_directory=args.artifacts)
    elif args.command == "ingest":
        output = import_historical_csv(
            args.input,
            args.output,
            source_name=args.source,
            station_column=args.station_column,
            timestamp_column=args.timestamp_column,
            value_column=args.value_column,
            rainfall_column=args.rainfall_column,
            latitude_column=args.latitude_column,
            longitude_column=args.longitude_column,
        )
    elif args.command == "predict":
        service = HydroLinkInferenceService(args.artifacts)
        output = service.analyze(
            station_id=args.station_id,
            name=args.station_id,
            value_m=args.value_m,
            timestamp=args.timestamp,
            source="cli_input",
        )
    else:
        raise AssertionError(args.command)
    print(json.dumps(output, indent=2, default=str))
    return 0

