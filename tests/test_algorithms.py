"""Behaviour of the three Lua algorithms, through ``acquire_sync()``.

The scripts read the server's ``TIME``. Most tests let a script reserve slots
ahead and record the sleeps the limiter would take, so no real time passes;
the few that need it use a short real sleep.
"""

import math
import time
import uuid
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pytest_mock import MockerFixture
from redis import Redis

from conftest import ALGORITHMS, MakeLimiter, bucket_of
from ratelimit_io import Algorithm, Limit, RateLimiter, RateLimitExceededError


def _server_time_us(client: Redis, seconds_ago: float = 0) -> int:
    """Return the server's clock, as the scripts read it, ``seconds_ago`` back."""
    seconds, microseconds = client.time()

    return round((seconds - seconds_ago) * 1_000_000) + microseconds


def _allowed(limiter: RateLimiter, key: str, limit: Limit, attempts: int) -> int:
    allowed = 0
    for _ in range(attempts):
        try:
            limiter.acquire_sync(key, limit=limit)
        except RateLimitExceededError:
            continue

        allowed += 1

    return allowed


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    algorithm=st.sampled_from(ALGORITHMS),
    requests=st.integers(min_value=1, max_value=15),
    attempts=st.integers(min_value=0, max_value=30),
)
def test__algorithm__burst__allows_exactly_the_limit(
    make_limiter: MakeLimiter, algorithm: Algorithm, requests: int, attempts: int
) -> None:
    limiter = make_limiter(algorithm=algorithm)
    limit = Limit(requests, minutes=1)

    allowed = _allowed(limiter, uuid.uuid4().hex, limit, attempts)

    assert allowed == min(requests, attempts)


@pytest.mark.parametrize('algorithm', [Algorithm.FIXED_WINDOW, Algorithm.SLIDING_WINDOW])
def test__window__exhausted__retry_after_is_the_rest_of_the_period(
    make_limiter: MakeLimiter, algorithm: Algorithm, key: str
) -> None:
    limiter = make_limiter(algorithm=algorithm)
    limit = Limit(1, minutes=1)
    limiter.acquire_sync(key, limit=limit)

    with pytest.raises(RateLimitExceededError) as caught:
        limiter.acquire_sync(key, limit=limit)

    assert 55 < caught.value.retry_after <= 60


@pytest.mark.parametrize('algorithm', [Algorithm.FIXED_WINDOW, Algorithm.SLIDING_WINDOW])
def test__window__exhausted__retry_after_counts_from_the_first_request(
    make_limiter: MakeLimiter, algorithm: Algorithm, key: str
) -> None:
    limiter = make_limiter(algorithm=algorithm)
    limit = Limit(2, seconds=1)
    limiter.acquire_sync(key, limit=limit)
    time.sleep(0.3)
    limiter.acquire_sync(key, limit=limit)

    with pytest.raises(RateLimitExceededError) as caught:
        limiter.acquire_sync(key, limit=limit)

    # The fixed window opened with the first request, and the first request is
    # the one the sliding window waits out; the second one says 1 s.
    assert caught.value.retry_after < 0.75


def test__gcra__exhausted__retry_after_is_one_emission_interval(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(algorithm=Algorithm.GCRA)
    limit = Limit(3, minutes=1)
    _allowed(limiter, key, limit, attempts=3)

    with pytest.raises(RateLimitExceededError) as caught:
        limiter.acquire_sync(key, limit=limit)

    assert 15 < caught.value.retry_after <= 20


def test__algorithm__refusal__leaves_the_bucket_untouched(
    limiter: RateLimiter, redis_client: Redis, key: str
) -> None:
    limit = Limit(1, minutes=1)
    limiter.acquire_sync(key, limit=limit)
    bucket = bucket_of(limiter, key, limit)
    before = redis_client.dump(bucket)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key, limit=limit)

    assert redis_client.dump(bucket) == before


def test__algorithm__allowed_request__bucket_expires_within_the_period(
    limiter: RateLimiter, redis_client: Redis, key: str
) -> None:
    limit = Limit(3, minutes=1)

    limiter.acquire_sync(key, limit=limit)

    assert 0 < redis_client.pttl(bucket_of(limiter, key, limit)) <= limit.period_ms()


@pytest.mark.parametrize(
    ('algorithm', 'expected'),
    [
        (Algorithm.FIXED_WINDOW, [1, 1, 2, 2]),
        (Algorithm.SLIDING_WINDOW, [1, 1, 2, 2]),
        (Algorithm.GCRA, [0.5, 1, 1.5, 2]),
    ],
)
def test__algorithm__waiting_requests__reserve_consecutive_slots(
    make_limiter: MakeLimiter,
    mocker: MockerFixture,
    algorithm: Algorithm,
    expected: list[float],
    key: str,
) -> None:
    limiter = make_limiter(algorithm=algorithm, max_wait=math.inf)
    limit = Limit(2, seconds=1)
    sleeps: list[float] = []
    mocker.patch('ratelimit_io._limiter.time', SimpleNamespace(sleep=sleeps.append))

    for _ in range(6):
        limiter.acquire_sync(key, limit=limit)

    assert sleeps == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize(
    ('algorithm', 'apart'),
    [(Algorithm.FIXED_WINDOW, False), (Algorithm.SLIDING_WINDOW, True)],
)
def test__window__staggered_requests__free_their_slots_one_by_one(
    make_limiter: MakeLimiter,
    mocker: MockerFixture,
    algorithm: Algorithm,
    apart: bool,
    key: str,
) -> None:
    limiter = make_limiter(algorithm=algorithm, max_wait=math.inf)
    limit = Limit(2, seconds=1)
    limiter.acquire_sync(key, limit=limit)
    time.sleep(0.3)
    limiter.acquire_sync(key, limit=limit)
    sleeps: list[float] = []
    mocker.patch('ratelimit_io._limiter.time', SimpleNamespace(sleep=sleeps.append))

    limiter.acquire_sync(key, limit=limit)
    limiter.acquire_sync(key, limit=limit)

    # The sliding window frees a slot as each request leaves it, 0.3 s apart;
    # the fixed window frees both when it ends.
    first, second = sleeps
    assert (second - first > 0.2) is apart


def test__fixed_window__bucket_without_expiry__still_ends_its_window(
    make_limiter: MakeLimiter, redis_client: Redis, key: str
) -> None:
    limiter = make_limiter()
    limit = Limit(1, minutes=1)
    bucket = bucket_of(limiter, key, limit)
    window_start = _server_time_us(redis_client, seconds_ago=61)
    redis_client.hset(bucket, mapping={'start': window_start, 'count': 1})

    limiter.acquire_sync(key, limit=limit)

    assert 0 < redis_client.pttl(bucket) <= limit.period_ms()


def test__algorithm__reservation__keeps_the_bucket_until_its_slot_has_passed(
    limiter: RateLimiter, redis_client: Redis, key: str, mocker: MockerFixture
) -> None:
    limit = Limit(1, minutes=1)
    limiter.acquire_sync(key, limit=limit)
    mocker.patch('ratelimit_io._limiter.time', SimpleNamespace(sleep=lambda _: None))

    limiter.acquire_sync(key, limit=limit, max_wait=math.inf)

    assert redis_client.pttl(bucket_of(limiter, key, limit)) > limit.period_ms()


@pytest.mark.parametrize(
    ('seconds_ago', 'allowed'),
    [(3600, 3), (40, 2)],
    ids=['idle-for-an-hour', 'two-intervals-drained'],
)
def test__gcra__full_backlog__drains_with_time(
    make_limiter: MakeLimiter, redis_client: Redis, key: str, seconds_ago: int, allowed: int
) -> None:
    limiter = make_limiter(algorithm=Algorithm.GCRA)
    limit = Limit(3, minutes=1)
    redis_client.hset(
        bucket_of(limiter, key, limit),
        mapping={
            'written': _server_time_us(redis_client, seconds_ago),
            'backlog': limit.period_ms() * 1000 * limit.requests,
        },
    )

    # A burst never grows past the limit, however long the bucket idled.
    assert _allowed(limiter, key, limit, attempts=5) == allowed


def test__sliding_window__entries_a_period_old__are_dropped(
    make_limiter: MakeLimiter, redis_client: Redis, key: str
) -> None:
    limiter = make_limiter(algorithm=Algorithm.SLIDING_WINDOW)
    limit = Limit(2, minutes=1)
    bucket = bucket_of(limiter, key, limit)
    an_hour_ago = _server_time_us(redis_client, seconds_ago=3600)
    redis_client.zadd(bucket, {f'old-{n}': an_hour_ago for n in range(5)})

    limiter.acquire_sync(key, limit=limit)

    assert redis_client.zcard(bucket) == 1
