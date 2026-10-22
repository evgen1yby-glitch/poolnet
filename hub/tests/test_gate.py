"""Gate tests: caching, invalidation, rate limits, the admin requirement."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from hub.bot import MockTransport  # noqa: E402
from hub.gate import (  # noqa: E402
    Gate,
    MemberStatus,
    RateLimiter,
)

CHANNEL = -1001234567890
USER = 4242


def _gate(**kwargs):
    members = kwargs.pop("members", {(CHANNEL, USER): "member"})
    transport = kwargs.pop("transport", None) or MockTransport(members=members)
    return Gate(transport=transport, channel_id=CHANNEL, **kwargs), transport


async def test_member_passes():
    gate, transport = _gate()
    assert await gate.is_member(USER) is True
    assert ("getChatMember", CHANNEL, USER) in transport.calls


async def test_non_member_fails():
    gate, _ = _gate(members={})
    assert await gate.is_member(USER) is False


async def test_kicked_user_fails():
    gate, _ = _gate(members={(CHANNEL, USER): "kicked"})
    assert await gate.is_member(USER) is False


async def test_positive_result_is_cached():
    gate, transport = _gate()
    assert await gate.is_member(USER)
    assert await gate.is_member(USER)
    # Two membership checks, one API call: the throttling defence.
    assert transport.calls.count(("getChatMember", CHANNEL, USER)) == 1
    assert gate.cache_hits == 1
    assert gate.api_calls == 1


async def test_chat_member_update_invalidates_instantly():
    gate, transport = _gate()
    assert await gate.is_member(USER)
    gate.on_chat_member_update(CHANNEL, USER, "member", "left")
    # A revoked member must not keep access for the remainder of the TTL.
    transport.members[(CHANNEL, USER)] = "left"
    assert await gate.is_member(USER, force=True) is False
    assert transport.calls.count(("getChatMember", CHANNEL, USER)) == 2


async def test_rate_limited_lookup_is_unknown_not_member():
    transport = MockTransport(members={(CHANNEL, USER): "member"}, rate_limit_after=0)
    gate = Gate(transport=transport, channel_id=CHANNEL)
    result = await gate.check(USER, force=True)
    assert result.status == MemberStatus.UNKNOWN
    assert result.retry_after == 1.0
    assert gate.rate_limited == 1
    # A rate-limited answer is not cached: it is a fact about us, not the user.
    assert await gate.is_member(USER, force=True) is False


async def test_recheck_cooldown_blocks_hammering():
    gate, transport = _gate()
    gate._cache.pop((CHANNEL, USER), None)
    gate.cooldown = 3600
    first = await gate.check(USER, force=True)
    second = await gate.check(USER, force=True)
    assert not first.is_unknown
    assert second.status == first.status
    assert transport.calls.count(("getChatMember", CHANNEL, USER)) == 1


async def test_admin_ok_requires_bot_membership():
    """Demote the bot and the gate must notice.

    Uses *one* transport for both halves, and that is the correction. The old
    shape built a second, different `MockTransport` — default `bot_id=42` — and
    scripted `(CHANNEL, 7)` into it, i.e. scripted a lookup for an id nobody
    would ever ask about. It then asserted `False`, which was true, but true
    because the bot's real id was unscripted and fell through to "left": the
    demotion never took effect and the `False` came from the absence of a
    member. Two mechanisms produced one observable, so the test was evidence for
    neither, and it stayed green through a `MockTransport.bot_status` bug that
    broke `is_admin_ok` for every default-constructed transport.

    Scripting the *same* transport — the one `get_me` reports — means the lookup
    that changes is the lookup the gate actually makes.
    """
    transport = MockTransport(bot_id=7, bot_status="administrator", members={(CHANNEL, 7): "administrator"})
    gate = Gate(transport=transport, channel_id=CHANNEL)
    assert await gate.is_admin_ok() is True

    transport.members[(CHANNEL, 7)] = "left"
    assert await gate.is_admin_ok() is False


async def test_admin_ok_false_when_api_fails():
    transport = MockTransport(members={}, rate_limit_after=0)
    gate = Gate(transport=transport, channel_id=CHANNEL)
    assert await gate.is_admin_ok() is False


def test_rate_limiter_burst_and_refill():
    limiter = RateLimiter(rate=1.0, burst=2)
    assert limiter.allow("k", now=0.0)
    assert limiter.allow("k", now=0.0)
    assert not limiter.allow("k", now=0.0)
    assert limiter.allow("k", now=1.0)  # one token refilled per second


def test_rate_limiter_prunes_idle_buckets():
    limiter = RateLimiter(rate=1.0, burst=5)
    limiter.allow("a", now=100.0)
    limiter.allow("b", now=100.0)
    removed = limiter.prune(older_than=10.0, now=111.0)
    assert removed == 2
    assert limiter._buckets == {}


def test_rate_limiter_has_hard_bucket_cap_and_shared_overflow():
    limiter = RateLimiter(rate=0.0, burst=1, max_buckets=2, idle_ttl=1000)
    assert limiter.allow("known", now=100.0)
    assert limiter.allow("other", now=100.0)
    assert not limiter.allow("attacker-1", now=100.0)
    assert not limiter.allow("attacker-2", now=100.0)
    assert len(limiter._buckets) == 2
    assert not limiter.allow("known", now=100.0)


def test_rate_limiter_does_not_refill_when_clock_moves_backwards():
    limiter = RateLimiter(rate=1.0, burst=2, idle_ttl=1000)
    assert limiter.allow("k", now=10.0)
    assert limiter.allow("k", now=10.0)
    assert not limiter.allow("k", now=10.0)
    assert not limiter.allow("k", now=0.0)
    assert len(limiter._buckets) == 1


def test_rate_limiter_validates_configuration():
    with pytest.raises(ValueError):
        RateLimiter(rate=-1.0, burst=1)
    with pytest.raises(ValueError):
        RateLimiter(rate=1.0, burst=0)
    with pytest.raises(ValueError):
        RateLimiter(rate=1.0, burst=1, max_buckets=0)


def test_forget_clears_user():
    gate, _ = _gate()
    gate._cache[(CHANNEL, USER)] = None
    gate._last_press[USER] = 1.0
    gate.forget(USER)
    assert (CHANNEL, USER) not in gate._cache
    assert USER not in gate._last_press


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
