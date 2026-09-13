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


@dataclass(frozen=True)
class OutputReservation:
    request_id: str
    tenant_id: str
    output_tokens: int


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
        self._pending: dict[str, float] = {}
        self._reservations: dict[int, OutputReservation] = {}
        self._request_reservations: dict[str, set[int]] = {}
        self._next_reservation = 0
        self._next_sequence = 0

    @property
    def counters(self) -> dict[str, float]:
        return dict(self._counters)

    @property
    def pending_service(self) -> dict[str, float]:
        return {
            tenant_id: self._pending.get(tenant_id, 0.0)
            for tenant_id in self._counters
        }

    @property
    def effective_counters(self) -> dict[str, float]:
        return {
            tenant_id: counter + self._pending.get(tenant_id, 0.0)
            for tenant_id, counter in self._counters.items()
        }

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
                self._counters[t] + self._pending.get(t, 0.0)
                for t in active
                if t in self._counters
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

    def reserve_output(self, request_id: str, output_tokens: int) -> int:
        """Reserve output service for one scheduled in-flight batch."""
        if output_tokens < 0:
            raise ValueError("output_tokens must be non-negative")
        tenant_id = self.tenant_for(request_id)
        reservation_id = self._next_reservation
        self._next_reservation += 1
        self._reservations[reservation_id] = OutputReservation(
            request_id=request_id,
            tenant_id=tenant_id,
            output_tokens=output_tokens,
        )
        self._pending[tenant_id] = (
            self._pending.get(tenant_id, 0.0) + output_tokens * self.wq
        )
        self._request_reservations.setdefault(request_id, set()).add(reservation_id)
        return reservation_id

    def settle_output(self, reservation_id: int, accepted_tokens: int) -> bool:
        """Replace one pending reservation with confirmed output service."""
        if accepted_tokens < 0:
            raise ValueError("accepted_tokens must be non-negative")
        reservation = self._reservations.get(reservation_id)
        if reservation is None:
            return False
        if accepted_tokens > reservation.output_tokens:
            raise ValueError("accepted_tokens exceed reserved output tokens")
        del self._reservations[reservation_id]
        request_reservations = self._request_reservations.get(reservation.request_id)
        if request_reservations is not None:
            request_reservations.discard(reservation_id)
            if not request_reservations:
                del self._request_reservations[reservation.request_id]
        tenant_id = reservation.tenant_id
        self._pending[tenant_id] -= reservation.output_tokens * self.wq
        self._counters[tenant_id] += accepted_tokens * self.wq
        return True

    def charge_tenant(self, tenant_id: str, output_tokens: int) -> None:
        if output_tokens < 0:
            raise ValueError("output_tokens must be non-negative")
        if tenant_id not in self._counters:
            raise KeyError(f"unknown tenant: {tenant_id}")
        self._counters[tenant_id] += output_tokens * self.wq

    def remove(self, request_id: str) -> None:
        """Forget request metadata while retaining the tenant's counter."""
        for reservation_id in tuple(self._request_reservations.get(request_id, ())):
            reservation = self._reservations.pop(reservation_id)
            self._pending[reservation.tenant_id] -= reservation.output_tokens * self.wq
        self._request_reservations.pop(request_id, None)
        self._requests.pop(request_id, None)

    def ordering_key(self, request_id: str) -> tuple[float, int, str]:
        """Order by counter, tenant FIFO sequence, then stable request id."""
        entry = self._requests[request_id]
        effective_counter = self._counters[entry.tenant_id] + self._pending.get(
            entry.tenant_id, 0.0
        )
        return effective_counter, entry.sequence, request_id

    def choose(self, request_ids: Iterable[str]) -> str:
        candidates = list(request_ids)
        if not candidates:
            raise IndexError("choose from an empty request set")
        return min(candidates, key=self.ordering_key)
