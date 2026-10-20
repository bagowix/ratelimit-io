"""The arithmetic of the Lua scripts, on a clock each test sets.

The real scripts read the server's ``TIME``, so a test that waits in real time
cannot tell a slot that frees a microsecond early from one that frees on time.
Here every script reads its clock from ``ARGV[5]`` and ``ARGV[6]`` instead and
appends the expiry it would set to a log, so each test pins exact numbers on
fakeredis and on a real server alike.
"""

import math
import uuid
from collections.abc import Callable

import pytest
from redis import Redis

from conftest import ALGORITHMS
from ratelimit_io import Algorithm, Limit
from ratelimit_io._scripts import SCRIPTS

# Close to the real clock, so the numbers are as large as a server's.
T0 = 1_760_000_000_000_000
SECOND = 1_000_000

ONE_PER_SECOND = Limit(1, seconds=1)
TWO_PER_SECOND = Limit(2, seconds=1)

# A third request at the moment two filled TWO_PER_SECOND waits for the next
# window, or for one emission interval under GCRA.
THIRD_REQUEST_WAITS = [
    (Algorithm.FIXED_WINDOW, 1000),
    (Algorithm.SLIDING_WINDOW, 1000),
    (Algorithm.GCRA, 500),
]

Take = Callable[..., int]


def clocked(algorithm: Algorithm) -> str:
    """Return the script of ``algorithm`` with the clock and the expiry under test control."""
    source = SCRIPTS[algorithm]
    assert "redis.call('TIME')" in source
    assert "redis.call('PEXPIRE', KEYS[1], " in source

    return source.replace("redis.call('TIME')", '{ARGV[5], ARGV[6]}').replace(
        "redis.call('PEXPIRE', KEYS[1], ", "redis.call('RPUSH', KEYS[2], "
    )


@pytest.fixture
def take(redis_client: Redis, prefix: str) -> Take:
    """Run a script on the test's bucket as the server would at ``at`` microseconds."""

    def take(algorithm: Algorithm, limit: Limit, at: int, max_wait_ms: float = 0) -> int:
        seconds, microseconds = divmod(at, SECOND)
        reply = redis_client.eval(
            clocked(algorithm),
            2,
            f'{prefix}:bucket',
            f'{prefix}:expiries',
            limit.requests,
            limit.period_ms(),
            max_wait_ms,
            uuid.uuid4().hex,
            seconds,
            microseconds,
        )

        return int(reply)

    return take


@pytest.fixture
def expiries(redis_client: Redis, prefix: str) -> Callable[[], list[int]]:
    """Return the expiries the scripts set on the test's bucket so far, in milliseconds."""

    def expiries() -> list[int]:
        return [int(ms) for ms in redis_client.lrange(f'{prefix}:expiries', 0, -1)]

    return expiries


@pytest.mark.parametrize(('requests', 'seconds'), [(11, 1), (18, 60), (13, 3600)])
def test__gcra__burst_within_one_microsecond__allows_exactly_the_limit(
    take: Take, requests: int, seconds: int
) -> None:
    limit = Limit(requests, seconds=seconds)

    replies = [take(Algorithm.GCRA, limit, T0) for _ in range(requests + 1)]

    assert replies[:-1] == [0] * requests
    assert replies[-1] < 0


@pytest.mark.parametrize('algorithm', ALGORITHMS)
def test__script__slot__frees_exactly_one_period_after_it_was_taken(
    take: Take, algorithm: Algorithm
) -> None:
    take(algorithm, ONE_PER_SECOND, T0)

    early = take(algorithm, ONE_PER_SECOND, T0 + SECOND - 1)
    on_time = take(algorithm, ONE_PER_SECOND, T0 + SECOND)

    assert (early, on_time) == (-1, 0)


@pytest.mark.parametrize(('algorithm', 'wait_ms'), THIRD_REQUEST_WAITS)
def test__script__wait_equal_to_the_budget__is_reserved(
    take: Take, algorithm: Algorithm, wait_ms: int
) -> None:
    take(algorithm, TWO_PER_SECOND, T0)
    take(algorithm, TWO_PER_SECOND, T0)

    reply = take(algorithm, TWO_PER_SECOND, T0, max_wait_ms=wait_ms)

    assert reply == wait_ms


@pytest.mark.parametrize(('algorithm', 'wait_ms'), THIRD_REQUEST_WAITS)
def test__script__wait_a_microsecond_over_the_budget__is_refused(
    take: Take, algorithm: Algorithm, wait_ms: int
) -> None:
    take(algorithm, TWO_PER_SECOND, T0)
    take(algorithm, TWO_PER_SECOND, T0)

    reply = take(algorithm, TWO_PER_SECOND, T0, max_wait_ms=wait_ms - 0.001)

    assert reply == -wait_ms


@pytest.mark.parametrize('algorithm', ALGORITHMS)
def test__script__wait_and_expiry_with_a_fraction_of_a_millisecond__round_up(
    take: Take, expiries: Callable[[], list[int]], algorithm: Algorithm
) -> None:
    take(algorithm, ONE_PER_SECOND, T0)

    reply = take(algorithm, ONE_PER_SECOND, T0 + 1, max_wait_ms=math.inf)

    assert reply == 1000
    assert expiries() == [1000, 2000]


@pytest.mark.parametrize('algorithm', ALGORITHMS)
def test__script__refusal__changes_neither_the_bucket_nor_its_expiry(
    take: Take,
    expiries: Callable[[], list[int]],
    redis_client: Redis,
    prefix: str,
    algorithm: Algorithm,
) -> None:
    take(algorithm, ONE_PER_SECOND, T0)
    before = redis_client.dump(f'{prefix}:bucket')

    reply = take(algorithm, ONE_PER_SECOND, T0 + 1)

    assert reply == -1000
    assert redis_client.dump(f'{prefix}:bucket') == before
    assert expiries() == [1000]
