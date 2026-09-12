"""Generate a deterministic JSON summary from request-level JSONL records."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def jain_index(values: Sequence[float]) -> float | None:
    if not values or not any(values):
        return None
    numerator = sum(values) ** 2
    denominator = len(values) * sum(value**2 for value in values)
    return numerator / denominator


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    by_tenant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_tenant[record["tenant_id"]].append(record)

    tenants: dict[str, Any] = {}
    services: list[float] = []
    all_output_tokens = 0
    for tenant_id, tenant_records in sorted(by_tenant.items()):
        successful = [record for record in tenant_records if record["status"] == "ok"]
        ttft = [
            record["first_token_time"] - record["arrival_time"]
            for record in successful
            if record.get("first_token_time") is not None
            and record.get("arrival_time") is not None
        ]
        output_tokens = sum(record.get("output_tokens") or 0 for record in successful)
        service = sum(
            (record.get("prompt_tokens") or 0) + (record.get("output_tokens") or 0)
            for record in successful
        )
        services.append(service)
        all_output_tokens += output_tokens
        tenants[tenant_id] = {
            "requests": len(tenant_records),
            "successful_requests": len(successful),
            "failed_requests": len(tenant_records) - len(successful),
            "weighted_service_tokens": service,
            "output_tokens": output_tokens,
            "ttft_seconds": {
                "p50": percentile(ttft, 0.50),
                "p95": percentile(ttft, 0.95),
                "p99": percentile(ttft, 0.99),
            },
        }

    arrivals = [record["arrival_time"] for record in records if record.get("arrival_time") is not None]
    endings = [record["end_time"] for record in records if record.get("end_time") is not None]
    elapsed = max(endings) - min(arrivals) if arrivals and endings else None
    return {
        "request_count": len(records),
        "tenant_count": len(tenants),
        "elapsed_seconds": elapsed,
        "output_throughput_tokens_per_second": (
            all_output_tokens / elapsed if elapsed and elapsed > 0 else None
        ),
        "service_gap_tokens": max(services) - min(services) if services else None,
        "jain_service_index": jain_index(services),
        "tenants": tenants,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", type=Path, help="Path to requests.jsonl")
    parser.add_argument("--output", type=Path, help="Defaults to analysis.json beside the input")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = args.output or args.requests.with_name("analysis.json")
    output.write_text(
        json.dumps(summarize(read_jsonl(args.requests)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
