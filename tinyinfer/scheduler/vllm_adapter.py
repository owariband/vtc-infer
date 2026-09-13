"""Minimal vLLM v0.29.0 adapter for the VTC scheduling state."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator

from vllm.v1.core.sched.async_scheduler import AsyncScheduler
from vllm.v1.core.sched.request_queue import RequestQueue
from vllm.v1.core.sched.scheduler import Scheduler
from vllm.v1.request import Request

from .vtc import VTCState
from tinyinfer.telemetry.metrics import SchedulerMetrics, scheduler_metrics


class CustomFCFSScheduler(Scheduler):
    """Unmodified vLLM FCFS scheduler loaded through ``scheduler_cls``.

    This control isolates the overhead of vLLM's custom synchronous scheduler
    path from the additional queueing and accounting performed by VTC.
    """


class CustomAsyncFCFSScheduler(AsyncScheduler):
    """Unmodified async FCFS control loaded through ``scheduler_cls``."""


class VTCRequestQueue(RequestQueue):
    def __init__(self, state: VTCState, metrics: SchedulerMetrics) -> None:
        self.state = state
        self.metrics = metrics
        self._requests: list[Request] = []

    def add_request(self, request: Request) -> None:
        self._requests.append(request)

    def pop_request(self) -> Request:
        request = self.peek_request()
        self._requests.remove(request)
        self.state.admit(request.request_id)
        self.metrics.record_decision()
        self.metrics.observe_state(self.state)
        return request

    def peek_request(self) -> Request:
        if not self._requests:
            raise IndexError("peek from an empty queue")
        started = time.perf_counter()
        request_id = self.state.choose(r.request_id for r in self._requests)
        self.metrics.observe_selection(time.perf_counter() - started)
        return next(r for r in self._requests if r.request_id == request_id)

    def prepend_request(self, request: Request) -> None:
        self.add_request(request)

    def prepend_requests(self, requests: RequestQueue) -> None:
        self._requests.extend(requests)

    def remove_request(self, request: Request) -> None:
        self._requests.remove(request)

    def remove_requests(self, requests: Iterable[Request]) -> None:
        removed = set(requests)
        self._requests = [r for r in self._requests if r not in removed]

    def __bool__(self) -> bool:
        return bool(self._requests)

    def __len__(self) -> int:
        return len(self._requests)

    def __iter__(self) -> Iterator[Request]:
        remaining = list(self._requests)
        while remaining:
            request_id = self.state.choose(r.request_id for r in remaining)
            request = next(r for r in remaining if r.request_id == request_id)
            remaining.remove(request)
            yield request


class VTCScheduler(AsyncScheduler):
    """Async vLLM scheduler with tenant-fair admission ordering."""

    DEFAULT_TENANT_ID = "__default__"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.vllm_config.speculative_config is not None:
            raise ValueError("VTCScheduler Day 2 does not support speculative decoding")
        if self.lora_config is not None:
            raise ValueError("VTCScheduler Day 2 does not support LoRA")
        if self.connector is not None:
            raise ValueError("VTCScheduler Day 2 does not support remote KV connectors")
        self.vtc = VTCState(
            wp=float(os.getenv("TINYINFER_VTC_WP", "1")),
            wq=float(os.getenv("TINYINFER_VTC_WQ", "2")),
        )
        self._vtc_metrics = scheduler_metrics()
        self._vtc_metrics.mark_build()
        self.waiting = VTCRequestQueue(self.vtc, self._vtc_metrics)
        self.skipped_waiting = VTCRequestQueue(self.vtc, self._vtc_metrics)
        self._vtc_batch_reservations: dict[int, dict[str, int]] = {}

    @staticmethod
    def _tenant_id(request: Request) -> str:
        extra_args = request.sampling_params.extra_args if request.sampling_params else None
        tenant_id = extra_args.get("tenant_id") if extra_args else None
        if not isinstance(tenant_id, str) or not tenant_id:
            # Exceptions escaping Scheduler.add_request terminate EngineCore in
            # vLLM 0.29.0 instead of becoming a per-request client error.
            return VTCScheduler.DEFAULT_TENANT_ID
        return tenant_id

    def add_request(self, request: Request) -> None:
        if request.request_id not in self.requests:
            tenant_id = self._tenant_id(request)
            active_tenants = {
                self.vtc.tenant_for(request_id)
                for request_id in self.requests
                if self.vtc.contains(request_id)
            }
            self.vtc.enqueue(
                request_id=request.request_id,
                tenant_id=tenant_id,
                input_tokens=request.num_prompt_tokens,
                active_tenants=active_tenants,
            )
        super().add_request(request)
        self._vtc_metrics.observe_state(self.vtc)

    def _update_after_schedule(self, scheduler_output) -> None:
        placeholders_before = {
            request_id: request.num_output_placeholders
            for request_id in scheduler_output.num_scheduled_tokens
            if (request := self.requests.get(request_id)) is not None
        }
        super()._update_after_schedule(scheduler_output)

        reservations: dict[str, int] = {}
        for request_id, previous in placeholders_before.items():
            request = self.requests.get(request_id)
            if request is None:
                continue
            reserved_tokens = request.num_output_placeholders - previous
            if reserved_tokens > 0:
                reservations[request_id] = self.vtc.reserve_output(
                    request_id, reserved_tokens
                )
        if reservations:
            self._vtc_batch_reservations[id(scheduler_output)] = reservations

    def update_from_output(self, scheduler_output, model_runner_output):
        reservations = self._vtc_batch_reservations.pop(id(scheduler_output), {})
        outputs = super().update_from_output(scheduler_output, model_runner_output)
        accepted: dict[str, int] = {}
        completed: set[str] = set()
        for client_outputs in outputs.values():
            for output in client_outputs.outputs:
                accepted[output.request_id] = accepted.get(output.request_id, 0) + len(
                    output.new_token_ids
                )
                if output.finish_reason is not None:
                    completed.add(output.request_id)
        for request_id, reservation_id in reservations.items():
            self.vtc.settle_output(
                reservation_id, accepted_tokens=accepted.get(request_id, 0)
            )
        for request_id in completed:
            self.vtc.remove(request_id)
        self._vtc_metrics.observe_state(self.vtc)
        return outputs

    def finish_requests(self, request_ids, finished_status):
        finished = super().finish_requests(request_ids, finished_status)
        for request in finished:
            self.vtc.remove(request.request_id)
        self._vtc_metrics.observe_state(self.vtc)
        return finished
