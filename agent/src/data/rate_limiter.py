"""Rate limiter for HTTP-based data sources.

Uses a token-bucket algorithm for sustained rate control plus adaptive
exponential backoff for error recovery. Designed to prevent IP bans when
pulling large volumes of data from THS/East Money/Tencent.

TDX (mootdx TCP) does NOT need rate limiting — its binary protocol is not
subject to HTTP-level rate limits.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from src.data.config import RateLimitConfig, config

logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Token-bucket rate limiter with adaptive backoff.

    Args:
        cfg: Rate-limit parameters. Defaults to the module-level config.

    Attributes:
        tokens: Current token count (fractional, for smooth refill).
        last_refill: ``time.monotonic()`` of the last token refill.
        consecutive_errors: Counter for adaptive backoff.
    """

    cfg: RateLimitConfig = field(default_factory=lambda: config.rate_limit)
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    consecutive_errors: int = 0

    # ── UA rotation ───────────────────────────────────────────────────

    _ua_index: int = field(default=0, init=False)

    @property
    def next_user_agent(self) -> str:
        """Return the next User-Agent string (round-robin)."""
        agents = config.user_agents
        if not agents:
            return "vibe-trading/1.0"
        ua = agents[self._ua_index % len(agents)]
        self._ua_index += 1
        return ua

    @property
    def proxy(self) -> Optional[dict[str, str]]:
        """Return proxy dict for ``requests`` if a proxy URL is configured."""
        if self.cfg.proxy_url:
            return {"http": self.cfg.proxy_url, "https": self.cfg.proxy_url}
        return None

    # ── token bucket ──────────────────────────────────────────────────

    def __post_init__(self) -> None:
        self.tokens = float(self.cfg.burst_size)
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(
            float(self.cfg.burst_size),
            self.tokens + elapsed * self.cfg.requests_per_second,
        )
        self.last_refill = now

    def acquire(self) -> float:
        """Wait until a token is available, then consume it.

        Returns:
            The delay in seconds that was actually waited (for logging).
        """
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0

        # Not enough tokens — sleep until one is available.
        wait = (1.0 - self.tokens) / self.cfg.requests_per_second
        # Add a small jitter (±10%) to avoid thundering-herd patterns.
        wait *= 0.9 + random.random() * 0.2
        time.sleep(wait)
        self.tokens = 0.0
        self.last_refill = time.monotonic()
        return wait

    # ── adaptive backoff ──────────────────────────────────────────────

    def on_success(self) -> None:
        """Reset consecutive error counter after a successful request."""
        if self.consecutive_errors > 0:
            logger.debug("RateLimiter: reset error count after %d errors", self.consecutive_errors)
        self.consecutive_errors = 0

    def on_error(self, exc: Exception | None = None) -> float:
        """Called after a failed request. Returns the backoff delay to wait.

        Uses exponential backoff: ``base * multiplier^errors``, capped at
        ``max_delay``, with ±25% jitter.
        """
        self.consecutive_errors += 1
        delay = self.cfg.base_delay_seconds * (
            self.cfg.backoff_multiplier ** (self.consecutive_errors - 1)
        )
        delay = min(delay, self.cfg.max_delay_seconds)
        # Add jitter to avoid synchronised retry waves.
        delay *= 0.75 + random.random() * 0.5
        logger.warning(
            "RateLimiter: error #%d (%.1fs backoff)%s",
            self.consecutive_errors,
            delay,
            f" — {exc}" if exc else "",
        )
        time.sleep(delay)
        return delay

    # ── batch pause ───────────────────────────────────────────────────

    def batch_pause(self) -> None:
        """Sleep for the configured batch pause duration.

        Call this after every ``batch_size`` requests to give the remote
        server breathing room.
        """
        if self.cfg.batch_pause_seconds > 0:
            logger.debug(
                "RateLimiter: batch pause %.1fs", self.cfg.batch_pause_seconds,
            )
            time.sleep(self.cfg.batch_pause_seconds)

    # ── context manager ───────────────────────────────────────────────

    def __enter__(self) -> RateLimiter:
        return self

    def __exit__(self, *args: object) -> None:
        pass
