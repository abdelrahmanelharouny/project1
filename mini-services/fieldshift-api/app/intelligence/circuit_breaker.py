"""Reusable async circuit breaker (A2).

Protects every LLM bridge consumer from hammering an unhealthy bridge:

    CLOSED   — normal operation; requests flow; failures increment a
               consecutive-failure counter.
    OPEN     — after `failure_threshold` consecutive failures every call
               fails FAST (CircuitOpenError) for `recovery_timeout` seconds;
               the bridge is not contacted at all.
    HALF_OPEN— after the timeout one probe call is allowed through
               (`half_open_attempts` total, serialized). Success closes the
               circuit; failure re-opens it and restarts the recovery clock.

State transitions are observable: every transition calls the registered
listeners and records the state in the AI metrics store. Async-safe: all
checkouts happen inside a single `asyncio.Lock` (single-event-loop atomic),
which is the right granularity for the FastAPI event loop. Threads that use
the SYNC bridge path share the same breaker — its `_maybe_probe`/`record_*`
methods are also guarded for thread safety with a threading.Lock around the
small state mutations, so one breaker instance serves both call styles.

The breaker never raises on success paths and never retries; retries belong
to the bridge client. Fallback policy (rules-only) stays with the callers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Awaitable, Callable

from app.intelligence import metrics
from app.intelligence.config import ai_settings

logger = logging.getLogger("croptwist.intelligence.circuit_breaker")

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised (fast-fail) when the circuit is open or probe budget is spent."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str = "llm_bridge",
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_attempts: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = (
            failure_threshold
            if failure_threshold is not None
            else ai_settings.llm_cb_failure_threshold
        )
        self.recovery_timeout = (
            recovery_timeout
            if recovery_timeout is not None
            else ai_settings.llm_cb_recovery_seconds
        )
        self.half_open_attempts = (
            half_open_attempts
            if half_open_attempts is not None
            else ai_settings.llm_cb_half_open_attempts
        )
        self._clock = clock
        self._state = CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_used = 0
        self._listeners: list[Callable[[str, str], None]] = []
        self._thread_lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> str:
        with self._thread_lock:
            return self._state

    def on_transition(self, listener: Callable[[str, str], None]) -> None:
        """Register a listener(old_state, new_state); exceptions are swallowed."""
        self._listeners.append(listener)

    def _transition(self, new_state: str) -> None:
        old = self._state
        if old == new_state:
            return
        self._state = new_state
        metrics.set_circuit_state(new_state)
        logger.warning(
            "circuit breaker '%s' transitioned %s -> %s", self.name, old, new_state
        )
        for listener in self._listeners:
            try:
                listener(old, new_state)
            except Exception:  # noqa: BLE001 — observability must not break calls
                logger.exception("circuit breaker listener failed")

    # ------------------------------------------------------------- admission
    def _try_admit(self) -> bool:
        """Synchronous admission check + state bookkeeping (thread-safe).

        Returns True when the caller may contact the bridge. May transition
        open -> half_open when the recovery timeout has elapsed.
        """
        with self._thread_lock:
            now = self._clock()
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                if (
                    self._opened_at is not None
                    and now - self._opened_at >= self.recovery_timeout
                ):
                    self._transition_locked(HALF_OPEN)
                    self._half_open_used = 1
                    return True  # this caller is the single probe
                return False
            # HALF_OPEN: only the configured probe budget may pass.
            if self._half_open_used < self.half_open_attempts:
                self._half_open_used += 1
                return True
            return False

    def _transition_locked(self, new_state: str) -> None:
        # Called with _thread_lock held (or from single-threaded async paths).
        self._transition(new_state)

    # ---------------------------------------------------------------- async
    async def aacquire(self) -> None:
        """Async admission: raises CircuitOpenError when the call must fail fast."""
        async with self._async_lock:
            if not self._try_admit():
                raise CircuitOpenError(
                    f"circuit '{self.name}' is {self._state} — failing fast"
                )

    def acquire(self) -> None:
        """Sync admission (threadpool callers). Raises CircuitOpenError."""
        if not self._try_admit():
            raise CircuitOpenError(
                f"circuit '{self.name}' is {self._state} — failing fast"
            )

    # --------------------------------------------------------------- records
    def record_success(self) -> None:
        with self._thread_lock:
            self._consecutive_failures = 0
            self._half_open_used = 0
            self._transition_locked(CLOSED)

    def record_failure(self) -> None:
        with self._thread_lock:
            self._consecutive_failures += 1
            if self._state == HALF_OPEN:
                self._reopen_locked()
            elif (
                self._state == CLOSED
                and self._consecutive_failures >= self.failure_threshold
            ):
                self._opened_at = self._clock()
                self._transition_locked(OPEN)

    def _reopen_locked(self) -> None:
        self._opened_at = self._clock()
        self._half_open_used = 0
        self._transition_locked(OPEN)

    def reset(self) -> None:
        """Test/ops helper: back to CLOSED with zeroed counters."""
        with self._thread_lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_used = 0
            self._transition_locked(CLOSED)

    # ------------------------------------------------------------- decorator
    async def arun(self, coro_factory: Callable[[], Awaitable[Any]]) -> Any:
        """Run an async call under the breaker: admit -> await -> record.

        `coro_factory` is a zero-arg callable returning the awaitable so the
        call is only CREATED when admitted (no fire-and-forget leakage).
        """
        await self.aacquire()
        try:
            result = await coro_factory()
        except CircuitOpenError:
            raise
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result


breaker = CircuitBreaker(name="llm_bridge")
