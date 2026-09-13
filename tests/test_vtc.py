import pytest

from tinyinfer.scheduler.vtc import VTCState


def test_admission_and_decode_charge_use_configured_weights():
    state = VTCState(wp=1, wq=2)
    state.enqueue("a1", "a", input_tokens=10)
    state.admit("a1")
    state.charge_output("a1", 3)
    assert state.counters == {"a": 16}


def test_output_reservation_is_observable_until_settled():
    state = VTCState(wp=1, wq=2)
    state.enqueue("a1", "a", input_tokens=10)
    state.admit("a1")

    reservation = state.reserve_output("a1", 2)

    assert state.counters == {"a": 10}
    assert state.pending_service == {"a": 4}
    assert state.effective_counters == {"a": 14}

    assert state.settle_output(reservation, accepted_tokens=2)
    assert state.counters == {"a": 14}
    assert state.pending_service == {"a": 0}


def test_active_tenant_metrics_only_include_outstanding_requests():
    state = VTCState(wp=1, wq=2)
    state.enqueue("a1", "a", input_tokens=10)
    state.enqueue("b1", "b", input_tokens=4, active_tenants={"a"})

    assert state.active_tenant_count == 2
    assert state.active_service_gap == 0

    state.admit("a1")
    assert state.active_service_gap == 10

    state.remove("a1")
    assert state.active_tenant_count == 1
    assert state.active_service_gap == 0


def test_multiple_in_flight_batches_affect_ordering_and_settle_out_of_order():
    state = VTCState(wp=0, wq=2)
    state.enqueue("a1", "a", input_tokens=0)
    state.enqueue("b1", "b", input_tokens=0)
    first = state.reserve_output("a1", 1)
    second = state.reserve_output("a1", 1)

    assert state.choose(["a1", "b1"]) == "b1"
    snapshots = [state.counters["a"]]
    assert state.settle_output(second, accepted_tokens=1)
    snapshots.append(state.counters["a"])
    assert state.settle_output(first, accepted_tokens=1)
    snapshots.append(state.counters["a"])

    assert snapshots == [0, 2, 4]
    assert state.pending_service["a"] == 0


def test_cancelling_request_releases_all_pending_service():
    state = VTCState(wp=1, wq=2)
    state.enqueue("cancelled", "a", input_tokens=4)
    state.admit("cancelled")
    first = state.reserve_output("cancelled", 1)
    second = state.reserve_output("cancelled", 1)

    state.remove("cancelled")

    assert state.counters == {"a": 4}
    assert state.pending_service == {"a": 0}
    assert not state.settle_output(first, accepted_tokens=1)
    assert not state.settle_output(second, accepted_tokens=1)


def test_counter_lift_includes_pending_service():
    state = VTCState(wp=0, wq=2)
    state.enqueue("a1", "a", input_tokens=0)
    state.reserve_output("a1", 10)

    state.enqueue("b1", "b", input_tokens=0, active_tenants={"a"})

    assert state.counters["b"] == 20


def test_stale_output_reservation_settles_at_most_once():
    state = VTCState(wp=0, wq=2)
    state.enqueue("preempted", "a", input_tokens=0)
    reservation = state.reserve_output("preempted", 1)

    assert state.settle_output(reservation, accepted_tokens=1)
    confirmed = state.counters["a"]
    assert not state.settle_output(reservation, accepted_tokens=1)

    assert state.counters["a"] == confirmed == 2
    assert state.pending_service["a"] == 0


def test_settlement_charges_only_tokens_accepted_from_reservation():
    state = VTCState(wp=0, wq=2)
    state.enqueue("stopped", "a", input_tokens=0)
    reservation = state.reserve_output("stopped", 2)

    assert state.settle_output(reservation, accepted_tokens=1)

    assert state.counters["a"] == 2
    assert state.pending_service["a"] == 0


def test_selects_smallest_counter_and_preserves_tenant_fifo():
    state = VTCState()
    state.enqueue("b1", "b", input_tokens=2)
    state.enqueue("a1", "a", input_tokens=8)
    state.enqueue("a2", "a", input_tokens=1, active_tenants={"a"})
    assert state.choose(["a2", "b1", "a1"]) == "b1"
    state.admit("b1")
    state.charge_output("b1", 4)
    assert state.choose(["a2", "a1"]) == "a1"


def test_counter_lift_for_reactivated_tenant():
    state = VTCState()
    state.enqueue("a1", "a", input_tokens=100)
    state.admit("a1")
    state.remove("a1")
    state.enqueue("b1", "b", input_tokens=120)
    state.admit("b1")
    state.enqueue("a2", "a", input_tokens=1, active_tenants={"b"})
    assert state.counters["a"] == 120
    state.admit("a2")
    assert state.counters["a"] == 121


def test_counter_never_decreases_on_remove_or_charge():
    state = VTCState()
    state.enqueue("a1", "a", input_tokens=4)
    state.admit("a1")
    snapshots = [state.counters["a"]]
    state.charge_output("a1", 2)
    snapshots.append(state.counters["a"])
    state.remove("a1")
    snapshots.append(state.counters["a"])
    assert snapshots == sorted(snapshots)


def test_cancelled_waiting_request_is_removed_without_charge():
    state = VTCState()
    state.enqueue("cancelled", "a", input_tokens=4)
    state.remove("cancelled")
    assert state.counters["a"] == 0
    with pytest.raises(KeyError):
        state.tenant_for("cancelled")


def test_cancelled_admitted_request_is_not_refunded():
    state = VTCState()
    state.enqueue("cancelled", "a", input_tokens=4)
    state.admit("cancelled")
    state.remove("cancelled")
    assert state.counters["a"] == 4


def test_ties_are_deterministic_by_global_arrival_sequence():
    state = VTCState(wp=0, wq=0)
    state.enqueue("z", "tenant-z", input_tokens=0)
    state.enqueue("a", "tenant-a", input_tokens=0)
    assert state.choose({"a", "z"}) == "z"


def test_admission_cost_is_charged_exactly_once():
    state = VTCState()
    state.enqueue("a1", "a", input_tokens=4)
    state.admit("a1")
    state.admit("a1")
    assert state.counters["a"] == 4


@pytest.mark.parametrize("wp,wq", [(-1, 2), (1, -2), (float("inf"), 2)])
def test_rejects_invalid_weights(wp, wq):
    with pytest.raises(ValueError):
        VTCState(wp=wp, wq=wq)


def test_rejects_duplicate_requests_and_negative_tokens():
    state = VTCState()
    state.enqueue("a1", "a", input_tokens=1)
    with pytest.raises(ValueError, match="duplicate"):
        state.enqueue("a1", "a", input_tokens=1)
    with pytest.raises(ValueError, match="non-negative"):
        state.charge_output("a1", -1)
