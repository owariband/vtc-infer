"""Pure-Python state for Virtual Token Counter scheduling.

This module deliberately has no vLLM dependency so the fairness rules can be
tested without a GPU or a vLLM installation.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass
class RequestEntry:
    tenant_id: str
    sequence: int
    input_tokens: int
    admitted: bool = False


class VTCState:
    """Maintain tenant counters and deterministic request ordering."""

    def __init__(self, wp: float = 1.0, wq: float = 2.0) -> None:
        if not isfinite(wp) or wp < 0:
            raise ValueError("wp must be a finite non-negative number")
        if not isfinite(wq) or wq < 0:
            raise ValueError("wq must be a finite non-negative number")
        self.wp = wp
        self.wq = wq
        self._counters: dict[str, float] = {}
        self._requests: dict[str, RequestEntry] = {}
        self._next_sequence = 0

    @property
    def counters(self) -> dict[str, float]:
        return dict(self._counters)

    def tenant_for(self, request_id: str) -> str:
        return self._requests[request_id].tenant_id

    def contains(self, request_id: str) -> bool:
        return request_id in self._requests

    def enqueue(
        self,
        request_id: str,
        tenant_id: str,
        input_tokens: int,
        active_tenants: Iterable[str] = (),
    ) -> None:
        """Register one waiting request and apply counter lift if reactivated."""
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        if request_id in self._requests:
            raise ValueError(f"duplicate request_id: {request_id}")
        if input_tokens < 0:
            raise ValueError("input_tokens must be non-negative")

        active = set(active_tenants)
        current = self._counters.get(tenant_id, 0.0)
        if tenant_id not in active:
            active_values = [
                self._counters[t] for t in active if t in self._counters
            ]
            if active_values:
                current = max(current, min(active_values))

        self._counters[tenant_id] = current
        self._requests[request_id] = RequestEntry(
            tenant_id=tenant_id,
            sequence=self._next_sequence,
            input_tokens=input_tokens,
        )
        self._next_sequence += 1

    def admit(self, request_id: str) -> None:
        """Charge input cost exactly once when a request leaves waiting."""
        entry = self._requests[request_id]
        if not entry.admitted:
            self._counters[entry.tenant_id] += entry.input_tokens * self.wp
            entry.admitted = True

    def charge_output(self, request_id: str, output_tokens: int) -> None:
        """Charge only output tokens actually accepted by the engine."""
        self.charge_tenant(self.tenant_for(request_id), output_tokens)

    def charge_tenant(self, tenant_id: str, output_tokens: int) -> None:
        if output_tokens < 0:
            raise ValueError("output_tokens must be non-negative")
        if tenant_id not in self._counters:
            raise KeyError(f"unknown tenant: {tenant_id}")
        self._counters[tenant_id] += output_tokens * self.wq

    def remove(self, request_id: str) -> None:
        """Forget request metadata while retaining the tenant's counter."""
        self._requests.pop(request_id, None)

    def ordering_key(self, request_id: str) -> tuple[float, int, str]:
        """Order by counter, tenant FIFO sequence, then stable request id."""
        entry = self._requests[request_id]
        return self._counters[entry.tenant_id], entry.sequence, request_id

    def choose(self, request_ids: Iterable[str]) -> str:
        candidates = list(request_ids)
        if not candidates:
            raise IndexError("choose from an empty request set")
        return min(candidates, key=self.ordering_key)
