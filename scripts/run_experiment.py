"""Run one workload and persist its manifest and request-level records."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from benchmark.loadgen import run_load
from benchmark.schema import ExperimentManifest, WorkloadConfig


def _git_output(*args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _service_parameters(values: Sequence[str]) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"service parameter must use key=value: {value}")
        key, raw_value = value.split("=", 1)
        if not key:
            raise ValueError("service parameter key must not be empty")
        parameters[key] = raw_value
    return parameters


def _experiment_id(workload_name: str, policy: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{workload_name}-{policy}"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def _run(args: argparse.Namespace) -> Path:
    config = WorkloadConfig.from_yaml(args.workload)
    if args.endpoint:
        config = replace(config, endpoint=args.endpoint)
    if args.model:
        config = replace(config, model=args.model)

    experiment_id = args.experiment_id or _experiment_id(config.name, args.policy)
    result_dir = args.results_dir / experiment_id
    result_dir.mkdir(parents=True, exist_ok=False)

    manifest = ExperimentManifest(
        experiment_id=experiment_id,
        policy=args.policy,
        started_at=datetime.now(timezone.utc).isoformat(),
        git_commit=_git_output("rev-parse", "HEAD"),
        git_dirty=bool(_git_output("status", "--porcelain")),
        workload=config.to_dict(),
        service_parameters=_service_parameters(args.service_parameter),
    )
    _write_json(result_dir / "manifest.json", manifest.to_dict())

    records = await run_load(config, experiment_id, args.policy)
    records.sort(key=lambda record: (record.scheduled_time, record.request_id))
    with (result_dir / "requests.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    summary = {
        "experiment_id": experiment_id,
        "request_count": len(records),
        "successful_requests": sum(record.status == "ok" for record in records),
        "failed_requests": sum(record.status != "ok" for record in records),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(result_dir / "run_summary.json", summary)
    return result_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--policy", choices=("fcfs", "vtc", "vtc-miss"), required=True)
    parser.add_argument("--endpoint", help="Override the workload API endpoint")
    parser.add_argument("--model", help="Override the workload model")
    parser.add_argument("--experiment-id")
    parser.add_argument("--results-dir", type=Path, default=Path("results/runs"))
    parser.add_argument(
        "--service-parameter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Record a server setting in manifest.json; may be repeated",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result_dir = asyncio.run(_run(args))
    print(result_dir)


if __name__ == "__main__":
    main()
