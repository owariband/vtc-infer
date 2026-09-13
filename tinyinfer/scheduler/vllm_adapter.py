"""Minimal vLLM v0.29.0 adapter for the VTC scheduling state."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator

from vllm.v1.core.sched.request_queue import RequestQueue
from vllm.v1.core.sched.scheduler import Scheduler
from vllm.v1.request import Request

from .vtc import VTCState


class VTCRequestQueue(RequestQueue):
    def __init__(self, state: VTCState) -> None:
        self.state = state
        self._requests: list[Request] = []

    def add_request(self, request: Request) -> None:
        self._requests.append(request)

    def pop_request(self) -> Request:
        request = self.peek_request()
        self._requests.remove(request)
        self.state.admit(request.request_id)
        return request

    def peek_request(self) -> Request:
        if not self._requests:
            raise IndexError("peek from an empty queue")
        request_id = self.state.choose(r.request_id for r in self._requests)
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


class VTCScheduler(Scheduler):
    """vLLM Scheduler with tenant-fair ordering of waiting requests."""

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
        self.waiting = VTCRequestQueue(self.vtc)
        self.skipped_waiting = VTCRequestQueue(self.vtc)

    @staticmethod
    def _tenant_id(request: Request) -> str:
        extra_args = request.sampling_params.extra_args if request.sampling_params else None
        tenant_id = extra_args.get("tenant_id") if extra_args else None
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError(
                f"request {request.request_id!r} is missing vllm_xargs.tenant_id"
            )
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

    def update_from_output(self, scheduler_output, model_runner_output):
        before = {
            request_id: (request.num_output_tokens, self.vtc.tenant_for(request_id))
            for request_id in scheduler_output.num_scheduled_tokens
            if (request := self.requests.get(request_id)) is not None
        }
        outputs = super().update_from_output(scheduler_output, model_runner_output)
        completed: set[str] = set()
        for request_id, (previous, tenant_id) in before.items():
            request = self.requests.get(request_id)
            if request is not None:
                produced = request.num_output_tokens - previous
            else:
                produced = sum(
                    len(output.new_token_ids)
                    for client_outputs in outputs.values()
                    for output in client_outputs.outputs
                    if output.request_id == request_id
                )
            if produced > 0:
                self.vtc.charge_tenant(tenant_id, produced)
            if any(
                output.request_id == request_id and output.finish_reason is not None
                for client_outputs in outputs.values()
                for output in client_outputs.outputs
            ):
                completed.add(request_id)
        for request_id in completed:
            self.vtc.remove(request_id)
        return outputs

    def finish_requests(self, request_ids, finished_status):
        finished = super().finish_requests(request_ids, finished_status)
        for request in finished:
            self.vtc.remove(request.request_id)
        return finished
