"""A2 circuit breaker: state transitions, fast-fail, recovery, thread safety."""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.intelligence.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    HALF_OPEN,
    OPEN,
    CLOSED,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: FakeClock, **kwargs) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=3, recovery_timeout=30.0, half_open_attempts=1,
        clock=clock, **kwargs,
    )


def test_starts_closed_and_stays_closed_on_success():
    breaker = _breaker(FakeClock())
    assert breaker.state == CLOSED
    breaker.record_success()
    breaker.record_success()
    assert breaker.state == CLOSED


def test_opens_after_consecutive_failures():
    breaker = _breaker(FakeClock())
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state == OPEN


def test_open_fails_fast_without_probe():
    breaker = _breaker(FakeClock())
    for _ in range(3):
        breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.acquire()
    assert breaker.state == OPEN


def test_recovery_timeout_moves_to_half_open_with_single_probe():
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state == OPEN
    clock.advance(10)
    with pytest.raises(CircuitOpenError):
        breaker.acquire()  # still inside the recovery window
    clock.advance(20.5)  # past recovery_timeout (30s total)
    assert breaker.state == OPEN  # transition happens on next admission check
    assert breaker.acquire() is None  # the single probe passes
    assert breaker.state == HALF_OPEN
    with pytest.raises(CircuitOpenError):
        breaker.acquire()  # probe budget spent — fail fast again


def test_half_open_success_closes():
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(31)
    breaker.acquire()
    breaker.record_success()
    assert breaker.state == CLOSED
    # Consecutive-failure counter reset: one new failure must not reopen.
    breaker.record_failure()
    assert breaker.state == CLOSED


def test_half_open_failure_reopens_and_restarts_clock():
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(31)
    breaker.acquire()
    breaker.record_failure()
    assert breaker.state == OPEN
    clock.advance(5)
    with pytest.raises(CircuitOpenError):
        breaker.acquire()
    clock.advance(26)  # 31s after reopen
    assert breaker.acquire() is None  # new probe window reached


def test_async_admission_and_run():
    async def scenario():
        clock = FakeClock()
        breaker = _breaker(clock)
        async with asyncio.Lock():
            pass

        async def ok():
            return "value"

        assert await breaker.arun(ok) == "value"
        for _ in range(3):
            breaker.record_failure()
        with pytest.raises(CircuitOpenError):
            await breaker.arun(ok)

    asyncio.run(scenario())


def test_arun_records_failure_on_exception():
    async def scenario():
        breaker = _breaker(FakeClock())

        async def boom():
            raise ValueError("bridge down")

        for i in range(3):
            with pytest.raises(ValueError):
                await breaker.arun(boom)
        assert breaker.state == OPEN

    asyncio.run(scenario())


def test_state_transitions_are_observable():
    transitions: list[tuple[str, str]] = []
    clock = FakeClock()
    breaker = _breaker(clock)
    breaker.on_transition(lambda old, new: transitions.append((old, new)))
    for _ in range(3):
        breaker.record_failure()
    clock.advance(31)
    breaker.acquire()
    breaker.record_success()
    assert transitions == [(CLOSED, OPEN), (OPEN, HALF_OPEN), (HALF_OPEN, CLOSED)]


def test_concurrent_thread_use_never_corrupts_state():
    clock = FakeClock()
    breaker = _breaker(clock)
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for _ in range(200):
                try:
                    breaker.acquire()
                    if n % 4 == 0:
                        breaker.record_failure()
                    else:
                        breaker.record_success()
                except CircuitOpenError:
                    pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert breaker.state in (CLOSED, OPEN)
