"""Atomicity under concurrency, against a real server only.

fakeredis serialises commands in-process, so it would pass these tests even if
the scripts were not atomic. A real Redis or Valkey runs each script as one
step, and only that proves no two clients can take the same slot.
"""

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture
from redis.asyncio import Redis as AsyncRedis

from conftest import MakeLimiter, requires_real_redis
from ratelimit_io import Algorithm, Limit, RateLimitExceededError

LIMIT = Limit(10, minutes=1)
CALLERS = 50


def reserved_sleeps(algorithm: Algorithm) -> list[float]:
    """The sleeps of the callers that wait, when CALLERS race for LIMIT at once."""
    waiting = range(LIMIT.requests, CALLERS)
    if algorithm is Algorithm.GCRA:
        interval = LIMIT.total_seconds() / LIMIT.requests
        return [(slot - LIMIT.requests + 1) * interval for slot in waiting]

    return [slot // LIMIT.requests * LIMIT.total_seconds() for slot in waiting]


@requires_real_redis
def test__acquire_sync__threads_race_for_one_bucket__allow_exactly_the_limit(
    make_limiter: MakeLimiter, algorithm: Algorithm, key: str
) -> None:
    limiter = make_limiter(algorithm=algorithm)

    def attempt(_: int) -> bool:
        try:
            limiter.acquire_sync(key, limit=LIMIT)
        except RateLimitExceededError:
            return False

        return True

    with ThreadPoolExecutor(max_workers=CALLERS) as pool:
        allowed = sum(pool.map(attempt, range(CALLERS)))

    assert allowed == LIMIT.requests


@requires_real_redis
@pytest.mark.asyncio
async def test__acquire__tasks_race_for_one_bucket__allow_exactly_the_limit(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, algorithm: Algorithm, key: str
) -> None:
    limiter = make_limiter(async_redis_client, algorithm=algorithm)

    async def attempt() -> bool:
        try:
            await limiter.acquire(key, limit=LIMIT)
        except RateLimitExceededError:
            return False

        return True

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(attempt()) for _ in range(CALLERS)]

    assert sum(task.result() for task in tasks) == LIMIT.requests


@requires_real_redis
def test__acquire_sync__waiting_threads_race_for_one_bucket__reserve_consecutive_slots(
    make_limiter: MakeLimiter, algorithm: Algorithm, key: str, mocker: MockerFixture
) -> None:
    limiter = make_limiter(algorithm=algorithm, max_wait=math.inf)
    sleeps: list[float] = []
    mocker.patch('ratelimit_io._limiter.time', SimpleNamespace(sleep=sleeps.append))

    with ThreadPoolExecutor(max_workers=CALLERS) as pool:
        list(pool.map(lambda _: limiter.acquire_sync(key, limit=LIMIT), range(CALLERS)))

    assert sorted(sleeps) == pytest.approx(reserved_sleeps(algorithm), abs=1)


@requires_real_redis
@pytest.mark.asyncio
async def test__acquire__waiting_tasks_race_for_one_bucket__reserve_consecutive_slots(
    make_limiter: MakeLimiter,
    async_redis_client: AsyncRedis,
    algorithm: Algorithm,
    key: str,
    mocker: MockerFixture,
) -> None:
    limiter = make_limiter(async_redis_client, algorithm=algorithm, max_wait=math.inf)
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    mocker.patch('ratelimit_io._limiter.asyncio', SimpleNamespace(sleep=record))

    async with asyncio.TaskGroup() as group:
        for _ in range(CALLERS):
            group.create_task(limiter.acquire(key, limit=LIMIT))

    assert sorted(sleeps) == pytest.approx(reserved_sleeps(algorithm), abs=1)
