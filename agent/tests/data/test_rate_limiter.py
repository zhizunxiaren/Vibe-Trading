"""Tests for RateLimiter (token-bucket + adaptive backoff)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.data.config import RateLimitConfig
from src.data.rate_limiter import RateLimiter


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def slow_cfg() -> RateLimitConfig:
    """A config with very slow rate so bucket behavior is observable."""
    return RateLimitConfig(
        requests_per_second=0.1,  # 1 token every 10 seconds
        burst_size=2,
        base_delay_seconds=0.001,
        max_delay_seconds=1.0,
        batch_size=5,
        batch_pause_seconds=0.01,
    )


@pytest.fixture
def fast_cfg() -> RateLimitConfig:
    """A config that never rate-limits (for testing non-blocking behavior)."""
    return RateLimitConfig(
        requests_per_second=1000.0,
        burst_size=1000,
        base_delay_seconds=0.0,
        max_delay_seconds=0.01,
        batch_size=1000,
        batch_pause_seconds=0.0,
    )


# ── Token bucket ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_initial_tokens_equal_burst() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(burst_size=7))
    assert rl.tokens == 7.0


@pytest.mark.unit
def test_acquire_consumes_token() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(burst_size=3, requests_per_second=1000.0))
    assert rl.tokens == 3.0
    rl.acquire()
    assert rl.tokens == pytest.approx(2.0, abs=0.1)


@pytest.mark.unit
def test_acquire_blocks_when_empty(slow_cfg: RateLimitConfig) -> None:
    """When burst is exhausted, acquire should sleep until a token refills."""
    rl = RateLimiter(cfg=slow_cfg)
    assert rl.tokens == 2.0

    # Consume all available tokens.
    rl.acquire()  # 2 → 1
    rl.acquire()  # 1 → 0

    # Next acquire should block (~10s wait for 1 token at 0.1 rps).
    t0 = time.monotonic()
    wait = rl.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed > 1.0, f"Expected blocking wait, got {elapsed:.2f}s"
    assert wait > 0


@pytest.mark.unit
def test_acquire_no_block_with_high_burst(fast_cfg: RateLimitConfig) -> None:
    rl = RateLimiter(cfg=fast_cfg)
    for _ in range(100):
        wait = rl.acquire()
        assert wait == 0.0


# ── Adaptive backoff ────────────────────────────────────────────────────


@pytest.mark.unit
def test_on_success_resets_errors() -> None:
    rl = RateLimiter()
    rl.consecutive_errors = 5
    rl.on_success()
    assert rl.consecutive_errors == 0


@pytest.mark.unit
def test_on_error_increases_backoff() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(
        base_delay_seconds=0.01,
        backoff_multiplier=2.0,
        max_delay_seconds=0.2,
    ))
    # First error: 0.01 * 2^0 = 0.01
    delay1 = rl.on_error()
    assert rl.consecutive_errors == 1
    assert delay1 >= 0.005  # jitter range: 0.0075-0.015

    # Second error: 0.01 * 2^1 = 0.02
    delay2 = rl.on_error()
    assert rl.consecutive_errors == 2
    assert delay2 >= 0.01  # jitter range: 0.015-0.03


@pytest.mark.unit
def test_backoff_capped_at_max() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(
        base_delay_seconds=0.01,
        backoff_multiplier=10.0,
        max_delay_seconds=0.05,
    ))
    # After many errors, delay should be capped at max_delay.
    for _ in range(10):
        rl.on_error()
    delay = rl.on_error()
    assert delay <= 0.075  # max * 1.5 (jitter upper bound)


# ── UA rotation ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_next_user_agent_rotates() -> None:
    rl = RateLimiter()
    ua1 = rl.next_user_agent
    ua2 = rl.next_user_agent
    ua3 = rl.next_user_agent
    # Should cycle through the 3 agents.
    assert ua1 != ua2
    assert ua2 != ua3
    ua4 = rl.next_user_agent
    assert ua4 == ua1  # Wraps around.


# ── Proxy ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_proxy_returns_none_when_not_configured() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(proxy_url=""))
    assert rl.proxy is None


@pytest.mark.unit
def test_proxy_returns_dict_when_configured() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(proxy_url="http://127.0.0.1:7890"))
    assert rl.proxy == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}


# ── Batch pause ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_batch_pause_sleeps() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(batch_pause_seconds=0.05))
    t0 = time.monotonic()
    rl.batch_pause()
    assert time.monotonic() - t0 >= 0.04  # allow small time variance


@pytest.mark.unit
def test_batch_pause_noop_when_zero() -> None:
    rl = RateLimiter(cfg=RateLimitConfig(batch_pause_seconds=0.0))
    t0 = time.monotonic()
    rl.batch_pause()
    assert time.monotonic() - t0 < 0.05


# ── Context manager ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_context_manager() -> None:
    with RateLimiter() as rl:
        assert rl.tokens > 0
    # Exiting should be a no-op (no exception).
