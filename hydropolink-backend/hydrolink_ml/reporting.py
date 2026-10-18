"""Write inspectable JSON and Markdown evaluation reports from executed results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_evaluation_report(output_dir: Path, results: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evaluation_metrics.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    dataset = results["dataset"]
    anomaly = results["anomaly_test"]
    forecast = results["forecast_test"]
    runtime = results["runtime"]
    lines = [
        "# HydroLink SA ML Evaluation Report",
        "",
        f"Generated from executed pipeline run `{results['run_id']}`.",
        "",
        "## Dataset and provenance",
        "",
        f"- Data mode: **{dataset['data_mode']}**",
        f"- Sources: {', '.join(dataset['sources'])}",
        f"- Stations: {dataset['stations']}",
        f"- Total clean observations: {dataset['total_observations']}",
        f"- Real observations: {dataset['real_observations']}",
        f"- Synthetic observations: {dataset['synthetic_observations']}",
        f"- Training/validation/test observations: {dataset['train_observations']} / {dataset['validation_observations']} / {dataset['test_observations']}",
        f"- Training period: {dataset['training_period']}",
        f"- Validation period: {dataset['validation_period']}",
        f"- Test period: {dataset['test_period']}",
        "",
        "Synthetic faults were injected independently into validation and test periods. Normal-behaviour models were trained only on the clean training period.",
        "",
        "## Anomaly detection",
        "",
        "| Metric | Held-out test value |",
        "|---|---:|",
    ]
    for key in ("precision", "recall", "f1", "false_positive_rate", "samples"):
        lines.append(f"| {key} | {_fmt(anomaly[key])} |")
    lines.extend(["", "### Detection by injected fault", "", "| Fault | Samples | Recall |", "|---|---:|---:|"])
    for fault, metrics in anomaly["by_fault"].items():
        lines.append(f"| {fault} | {metrics['samples']} | {_fmt(metrics['recall'])} |")
    lines.extend(
        [
            "",
            "## Forecasting",
            "",
            f"Forecast horizon: **{results['configuration']['forecast']['horizon_steps']} hourly steps**.",
            "",
            "| Metric | Selected model | Persistence | Historical average |",
            "|---|---:|---:|---:|",
            f"| MAE (m) | {_fmt(forecast['mae'])} | {_fmt(forecast['persistence_mae'])} | {_fmt(forecast['historical_average_mae'])} |",
            f"| RMSE (m) | {_fmt(forecast['rmse'])} | {_fmt(forecast['persistence_rmse'])} | {_fmt(forecast['historical_average_rmse'])} |",
            "",
            f"Prediction-interval coverage: **{_fmt(forecast['interval_coverage'])}**; mean width: **{_fmt(forecast['mean_interval_width'])} m**.",
            "",
            "### Forecast model by station",
            "",
            "| Station | Selected algorithm | Samples | MAE | RMSE | Coverage |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for station_id, metrics in forecast["by_station"].items():
        lines.append(
            f"| {station_id} | {metrics['selected_algorithm']} | {metrics['samples']} | "
            f"{_fmt(metrics['mae'])} | {_fmt(metrics['rmse'])} | {_fmt(metrics['interval_coverage'])} |"
        )
    lines.extend(
        [
            "",
            "## Trust Score validation",
            "",
            "| Scenario | Mean score | Minimum | Maximum | Samples |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for scenario, metrics in results["trust_validation"].items():
        lines.append(
            f"| {scenario} | {_fmt(metrics['mean'])} | {_fmt(metrics['min'])} | {_fmt(metrics['max'])} | {metrics['samples']} |"
        )
    lines.extend(
        [
            "",
            "## Runtime and artifacts",
            "",
            f"- Offline training and evaluation: {_fmt(runtime['training_seconds'])} seconds",
            f"- Validated artifact loading: {_fmt(runtime['loading_milliseconds'])} ms",
            f"- Mean inference latency: {_fmt(runtime['mean_inference_milliseconds'])} ms",
            f"- Approximate predictions per second: {_fmt(runtime['predictions_per_second'])}",
            f"- Total artifact size: {runtime['artifact_bytes']} bytes",
            "",
            "## Known limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in results["limitations"])
    lines.extend(
        [
            "",
            "No result in this report is a training-set accuracy. Model selection used the validation period and all headline metrics use the untouched chronological test period.",
            "",
        ]
    )
    markdown_path = output_dir / "evaluation_report.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path

