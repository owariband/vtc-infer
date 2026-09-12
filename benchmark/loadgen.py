"""Async open-loop load generation for an OpenAI-compatible chat endpoint."""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

import httpx

from benchmark.schema import RequestRecord, TenantConfig, WorkloadConfig


@dataclass(frozen=True)
class ScheduledRequest:
    request_id: str
    tenant: TenantConfig
    scheduled_time: float
    prompt: str


RecordSink = Callable[[RequestRecord], Awaitable[None]]


def build_prompt(tenant: TenantConfig, request_index: int, seed: int) -> str:
    """Build a deterministic prompt with an approximately controlled token count."""
    prefix = tenant.prompt_prefix.strip()
    marker = f" tenant={tenant.tenant_id} request={request_index} seed={seed}."
    filler = " explain" * max(1, tenant.prompt_tokens - len(marker.split()))
    return f"{prefix}{marker}{filler}".strip()


def generate_schedule(config: WorkloadConfig) -> list[ScheduledRequest]:
    """Generate independent Poisson arrivals for every tenant."""
    rng = random.Random(config.seed)
    requests: list[ScheduledRequest] = []
    for tenant in config.tenants:
        scheduled_time = 0.0
        request_index = 0
        while True:
            scheduled_time += rng.expovariate(tenant.request_rate)
            if scheduled_time > config.duration_seconds:
                break
            request_index += 1
            requests.append(
                ScheduledRequest(
                    request_id=f"{tenant.tenant_id}-{request_index:06d}",
                    tenant=tenant,
                    scheduled_time=scheduled_time,
                    prompt=build_prompt(tenant, request_index, config.seed),
                )
            )
    return sorted(requests, key=lambda request: (request.scheduled_time, request.request_id))


def _sse_payloads(lines: Iterable[str]) -> Iterable[dict]:
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        yield json.loads(payload)


async def _send_request(
    client: httpx.AsyncClient,
    config: WorkloadConfig,
    experiment_id: str,
    policy: str,
    scheduled: ScheduledRequest,
    clock: Callable[[], float],
    start_time: float,
    semaphore: asyncio.Semaphore,
) -> RequestRecord:
    await asyncio.sleep(max(0.0, start_time + scheduled.scheduled_time - clock()))
    record = RequestRecord(
        experiment_id=experiment_id,
        request_id=scheduled.request_id,
        tenant_id=scheduled.tenant.tenant_id,
        policy=policy,
        scheduled_time=scheduled.scheduled_time,
        prompt_tokens=scheduled.tenant.prompt_tokens,
    )

    async with semaphore:
        record.arrival_time = clock() - start_time
        try:
            async with client.stream(
                "POST",
                config.endpoint,
                json={
                    "model": config.model,
                    "messages": [
                        *(
                            [{"role": "system", "content": scheduled.tenant.system_prompt}]
                            if scheduled.tenant.system_prompt
                            else []
                        ),
                        {"role": "user", "content": scheduled.prompt},
                    ],
                    "max_tokens": scheduled.tenant.max_output_tokens,
                    "temperature": 0,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "vllm_xargs": {"tenant_id": scheduled.tenant.tenant_id},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    for payload in _sse_payloads((line,)):
                        choices = payload.get("choices") or []
                        if choices:
                            content = choices[0].get("delta", {}).get("content")
                            if content:
                                if record.first_token_time is None:
                                    record.first_token_time = clock() - start_time
                        usage = payload.get("usage")
                        if usage:
                            record.prompt_tokens = usage.get("prompt_tokens")
                            record.output_tokens = usage.get("completion_tokens")
                            details = usage.get("prompt_tokens_details") or {}
                            record.cached_tokens = details.get("cached_tokens")
                record.status = "ok"
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            record.status = "error"
            record.error = f"{type(error).__name__}: {error}"
        finally:
            record.end_time = clock() - start_time
    return record


async def run_load(
    config: WorkloadConfig,
    experiment_id: str,
    policy: str,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> list[RequestRecord]:
    """Run all arrivals without coupling future arrivals to request completion."""
    schedule = generate_schedule(config)
    semaphore = asyncio.Semaphore(config.max_in_flight)
    timeout = httpx.Timeout(config.request_timeout_seconds)
    limits = httpx.Limits(
        max_connections=config.max_in_flight,
        max_keepalive_connections=config.max_in_flight,
    )
    start_time = clock()
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        tasks = [
            asyncio.create_task(
                _send_request(
                    client,
                    config,
                    experiment_id,
                    policy,
                    scheduled,
                    clock,
                    start_time,
                    semaphore,
                )
            )
            for scheduled in schedule
        ]
        return list(await asyncio.gather(*tasks))
