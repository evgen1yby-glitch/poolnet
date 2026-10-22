"""Telegram-gated subscriptions. Pure logic + a transport protocol.

The gate is a **correctness** component, not an optimisation: `getChatMember` is
only guaranteed to work when the bot is an **administrator** of the channel, the
method is rate-limited tightly and undocumented, and there is a documented case
of a bot temporarily banned for spamming it. So:

* successful lookups are cached per `(user_id, chat_id)` for `CACHE_TTL`;
* a `chat_member` transition out of the channel invalidates the entry *at once*;
* negative results are cached very briefly (a user who just joined should not
  be told "not a member" for 10 minutes);
* a 429 with `retry_after` suppresses the cache and is recorded as a metric.

The bot must be an admin. `is_admin_ok` lets the caller assert that at startup
and refuse to serve subscriptions until it is true — because a silent gate that
always returns False takes the whole service down and looks like a bug.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Protocol

#: Positive lookups: 10 minutes. Long enough that a chat with 5000 members does
#: not hammer the API, short enough that a revoked subscription is noticed.
CACHE_TTL_SECONDS = 600

#: Negative lookups: 30 s. Someone who just joined and pressed the button must
#: not be refused again immediately.
NEGATIVE_CACHE_TTL_SECONDS = 30

#: One "am I a member?" press per user per this many seconds.
RECHECK_COOLDOWN_SECONDS = 30

#: States that mean "is a member" (Telegram getChatMember `status`).
MEMBER_STATES = frozenset({"member", "administrator", "creator", "restricted"})
LEAVING_STATES = frozenset({"left", "kicked"})


class MemberStatus(str):
    MEMBER = "member"
    NOT_MEMBER = "not_member"
    UNKNOWN = "unknown"  # API error / rate limit: caller decides
    BLOCKED = "blocked"  # bot blocked by the user


@dataclass
class MembershipResult:
    status: str
    checked_at: float
    retry_after: Optional[float] = None

    @property
    def is_member(self) -> bool:
        return self.status == MemberStatus.MEMBER

    @property
    def is_unknown(self) -> bool:
        return self.status == MemberStatus.UNKNOWN


class BotTransport(Protocol):
    """The seam that makes the gate testable without Telegram."""

    async def get_chat_member(self, chat_id: int, user_id: int) -> str:
        """Return the raw Telegram status string.

        Raises `TransportError` on HTTP 429 / 5xx / network failure.
        """
        ...

    async def get_me(self) -> dict:
        ...


class TransportError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Gate:
    """Membership cache with invalidation and a re-check cooldown.

    Cache entries carry the raw status so a `chat_member` update can be turned
    into an invalidation without another API call.
    """

    transport: BotTransport
    channel_id: int
    cache_ttl: int = CACHE_TTL_SECONDS
    negative_ttl: int = NEGATIVE_CACHE_TTL_SECONDS
    cooldown: int = RECHECK_COOLDOWN_SECONDS
    _cache: dict[tuple[int, int], MembershipResult] = field(default_factory=dict, repr=False)
    _last_press: dict[int, float] = field(default_factory=dict, repr=False)
    # metrics: observable rate limiting, which is the only way to see Telegram's
    # silent throttling at all.
    api_calls: int = 0
    rate_limited: int = 0
    cache_hits: int = 0

    # -- public API ------------------------------------------------------

    async def is_member(self, user_id: int, *, force: bool = False) -> bool:
        """True only on a *known* member. Unknown fails closed for the caller.

        Unknown means "we could not check" (rate limit, outage). The caller
        decides: for a subscription lookup the safe choice is to serve anyway
        rather than lock a paying user out — but that is a policy decision at
        the call site, not here.

        `force` is accepted so a caller can bypass the cache without dropping
        down to `check`; without it, this convenience wrapper is unusable from
        the code path that has just been invalidated by a `chat_member` update.
        """
        result = await self.check(user_id, force=force)
        return result.is_member

    async def check(self, user_id: int, *, force: bool = False) -> MembershipResult:
        key = (self.channel_id, user_id)
        now = time.monotonic()

        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                ttl = self.cache_ttl if cached.is_member else self.negative_ttl
                if now - cached.checked_at < ttl:
                    self.cache_hits += 1
                    return cached

        # Cooldown is not part of the cache: it throttles the *API*, and the
        # only caller that asks for `force` is a human pressing /start or
        # /check (`bot.py`). So `force` bypasses the TTL but still honours the
        # cooldown — otherwise one impatient user hammering /check would burn
        # the bot's rate limit, which is what the cooldown exists to prevent.
        last_press = self._last_press.get(user_id)
        if last_press is not None and now - last_press < self.cooldown:
            # Within the cooldown there is no fresh answer to give, so a
            # cached one (if any) is the best available truth.
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            return MembershipResult(MemberStatus.UNKNOWN, now)

        self._last_press[user_id] = now
        self.api_calls += 1
        try:
            raw = await self.transport.get_chat_member(self.channel_id, user_id)
        except TransportError as exc:
            self.rate_limited += 1
            result = MembershipResult(MemberStatus.UNKNOWN, now, retry_after=exc.retry_after)
            # Do not cache a rate-limited answer: it is a statement about us,
            # not about the user.
            self._cache.pop(key, None)
            return result

        result = MembershipResult(self._normalise(raw), now)
        self._cache[key] = result
        return result

    def on_chat_member_update(self, chat_id: int, user_id: int, old: str, new: str) -> None:
        """Handle a `chat_member` update. Called by the bot's dispatcher.

        Invalidation is instant: a user who left while their positive entry was
        still cached must not keep getting access for another 10 minutes.

        Every transition invalidates — enters, exits, and in-channel
        promotions alike. A promotion inside the channel does not change the
        answer, but re-deriving it once is cheaper than reasoning about which
        transitions could possibly matter.

        The cooldown is dropped with the cache entry. Telegram just told us the
        cached answer is *wrong*, which is the one situation where re-checking
        immediately is required rather than throttled — keeping `_last_press`
        would make the next lookup answer from the now-empty cache and report
        "unknown" for a user we have just been told has left.
        """
        self._cache.pop((chat_id, user_id), None)
        self._last_press.pop(user_id, None)

    def forget(self, user_id: int) -> None:
        self._cache.pop((self.channel_id, user_id), None)
        self._last_press.pop(user_id, None)

    # -- admin assertion -------------------------------------------------

    async def is_admin_ok(self) -> bool:
        """True when the bot can actually call `getChatMember` on the channel.

        The bot must be an administrator; otherwise `getChatMember` may return
        wrong answers and the gate silently rejects everyone.
        """
        try:
            me = await self.transport.get_me()
        except TransportError:
            return False
        bot_id = int(me.get("id", 0))
        try:
            status = await self.transport.get_chat_member(self.channel_id, bot_id)
        except TransportError:
            return False
        return status in MEMBER_STATES

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _normalise(raw: str) -> str:
        status = (raw or "").lower()
        if status in LEAVING_STATES:
            return MemberStatus.NOT_MEMBER
        if status in MEMBER_STATES:
            return MemberStatus.MEMBER
        return MemberStatus.UNKNOWN


@dataclass
class RateLimiter:
    """Token bucket. Two buckets per subscription identity.

    Per-token (a client polling on a short interval) and per-IP (an enumerator).
    Both must be enforced, because they catch different attacks.
    """

    rate: float  # tokens per second
    burst: int
    max_buckets: int = 10_000
    idle_ttl: float = 3600.0
    _buckets: OrderedDict[str, tuple[float, float]] = field(
        default_factory=OrderedDict, repr=False
    )
    _last_prune: float = field(default_factory=time.monotonic, repr=False)

    def __post_init__(self) -> None:
        if self.rate < 0 or self.burst < 1:
            raise ValueError("rate must be non-negative and burst must be positive")
        if self.max_buckets < 1 or self.idle_ttl <= 0:
            raise ValueError("max_buckets and idle_ttl must be positive")

    def allow(self, key: str, *, now: Optional[float] = None) -> bool:
        """Consume one token while keeping memory bounded under unique-key floods."""
        stamp = time.monotonic() if now is None else now
        if stamp - self._last_prune >= min(60.0, self.idle_ttl):
            self.prune(self.idle_ttl, now=stamp)
            self._last_prune = stamp

        bucket_key = key
        bucket = self._buckets.get(bucket_key)
        if bucket is None and len(self._buckets) >= self.max_buckets - 1:
            # Reserve one slot for novel identities. They share this bucket, so a
            # key flood cannot evict and reset active clients' token state.
            bucket_key = "__overflow__"
            bucket = self._buckets.get(bucket_key)
        if bucket is None:
            tokens, last = float(self.burst), stamp
        else:
            tokens, last = bucket
            self._buckets.move_to_end(bucket_key)
        tokens = min(float(self.burst), tokens + max(0.0, stamp - last) * self.rate)
        allowed = tokens >= 1.0
        self._buckets[bucket_key] = (tokens - 1.0 if allowed else tokens, stamp)
        return allowed

    def prune(self, older_than: float | None = None, *, now: Optional[float] = None) -> int:
        """Drop idle buckets; called automatically and available for maintenance."""
        stamp = time.monotonic() if now is None else now
        ttl = self.idle_ttl if older_than is None else older_than
        stale = [key for key, (_, ts) in self._buckets.items() if stamp - ts > ttl]
        for key in stale:
            self._buckets.pop(key, None)
        return len(stale)
