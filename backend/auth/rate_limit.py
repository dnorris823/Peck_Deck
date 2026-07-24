"""Login throttling.

``/login`` is the one unauthenticated endpoint that checks a secret, which makes
it the natural target for credential stuffing. bcrypt makes each attempt costly
for the server too, so an unthrottled login is also a cheap denial-of-service.

Two independent windows, both required to pass:

* per **account** — stops an attacker grinding one known email from many IPs
* per **client IP** — stops one host spraying many accounts

State is in-memory, so it resets on restart and is per-process. That's a real
limitation under multiple workers (each keeps its own counters, so the effective
limit multiplies) — acceptable for a single-container home deployment, and the
obvious upgrade is Redis if this is ever scaled out.
"""
import time
from dataclasses import dataclass, field

# Failures allowed inside the window before lockout kicks in.
MAX_ATTEMPTS = 5
# Rolling window / lockout duration, seconds.
WINDOW_SECONDS = 300


@dataclass
class LoginRateLimiter:
    max_attempts: int = MAX_ATTEMPTS
    window_seconds: int = WINDOW_SECONDS
    # key -> list of failure timestamps (monotonic)
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(key, []) if now - t < self.window_seconds]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def is_locked(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic())) >= self.max_attempts

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest failure in the window ages out."""
        now = time.monotonic()
        recent = self._prune(key, now)
        if len(recent) < self.max_attempts:
            return 0
        return max(1, int(self.window_seconds - (now - min(recent))))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now)
        self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        """Clear a key's history — called on a successful login."""
        self._failures.pop(key, None)

    def clear(self) -> None:
        self._failures.clear()


login_rate_limiter = LoginRateLimiter()
