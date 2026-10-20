"""``acquire()`` / ``acquire_sync()``: waiting, keys, limits and clients."""

import asyncio
import math
import time
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture
from redis import ConnectionError as RedisConnectionError
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.backoff import NoBackoff
from redis.retry import Retry

from conftest import LONG, MakeLimiter
from ratelimit_io import Algorithm, Limit, RateLimiter, RateLimitExceededError

SHORT = Limit(1, seconds=0.2)
ONE = Limit(1, minutes=1)


def test__acquire_sync__under_limit__returns(limiter: RateLimiter, key: str) -> None:
    for _ in range(LONG.requests):
        limiter.acquire_sync(key)


def test__acquire_sync__over_limit__raises_with_retry_after(limiter: RateLimiter, key: str) -> None:
    for _ in range(LONG.requests):
        limiter.acquire_sync(key)

    with pytest.raises(RateLimitExceededError) as caught:
        limiter.acquire_sync(key)

    assert caught.value.limit == LONG
    assert 0 < caught.value.retry_after <= 60


@pytest.mark.asyncio
async def test__acquire__over_limit__raises_with_retry_after(
    async_limiter: RateLimiter, key: str
) -> None:
    for _ in range(LONG.requests):
        await async_limiter.acquire(key)

    with pytest.raises(RateLimitExceededError) as caught:
        await async_limiter.acquire(key)

    assert caught.value.limit == LONG
    assert 0 < caught.value.retry_after <= 60


def test__acquire_sync__max_wait__sleeps_until_its_slot_and_takes_it(
    make_limiter: MakeLimiter, algorithm: Algorithm, key: str
) -> None:
    limiter = make_limiter(max_wait=2, algorithm=algorithm)
    limiter.acquire_sync(key, limit=SHORT)
    started = time.monotonic()

    limiter.acquire_sync(key, limit=SHORT)

    assert time.monotonic() - started >= 0.1

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key, limit=SHORT, max_wait=0)


@pytest.mark.asyncio
async def test__acquire__max_wait__sleeps_until_its_slot_and_takes_it(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, algorithm: Algorithm, key: str
) -> None:
    limiter = make_limiter(async_redis_client, max_wait=2, algorithm=algorithm)
    await limiter.acquire(key, limit=SHORT)
    started = time.monotonic()

    await limiter.acquire(key, limit=SHORT)

    assert time.monotonic() - started >= 0.1

    with pytest.raises(RateLimitExceededError):
        await limiter.acquire(key, limit=SHORT, max_wait=0)


def test__acquire_sync__waiting__asks_redis_once_and_sleeps_once(
    make_limiter: MakeLimiter, algorithm: Algorithm, key: str, mocker: MockerFixture
) -> None:
    limiter = make_limiter(limit=ONE, max_wait=math.inf, algorithm=algorithm)
    limiter.acquire_sync(key)
    run = mocker.spy(limiter, '_run_sync')
    sleeps: list[float] = []
    mocker.patch('ratelimit_io._limiter.time', SimpleNamespace(sleep=sleeps.append))

    limiter.acquire_sync(key)

    assert run.call_count == 1
    assert sleeps == [pytest.approx(60, abs=1)]


@pytest.mark.asyncio
async def test__acquire__waiting__asks_redis_once_and_sleeps_once(
    make_limiter: MakeLimiter,
    async_redis_client: AsyncRedis,
    algorithm: Algorithm,
    key: str,
    mocker: MockerFixture,
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE, max_wait=math.inf, algorithm=algorithm)
    await limiter.acquire(key)
    run = mocker.spy(limiter, '_run')
    sleep = mocker.AsyncMock()
    mocker.patch('ratelimit_io._limiter.asyncio', SimpleNamespace(sleep=sleep))

    await limiter.acquire(key)

    assert run.call_count == 1
    sleep.assert_awaited_once_with(pytest.approx(60, abs=1))


def test__acquire_sync__next_slot_beyond_max_wait__raises_without_sleeping(
    make_limiter: MakeLimiter, key: str, mocker: MockerFixture
) -> None:
    limiter = make_limiter(max_wait=1)
    limiter.acquire_sync(key, limit=ONE)
    sleeps: list[float] = []
    mocker.patch('ratelimit_io._limiter.time', SimpleNamespace(sleep=sleeps.append))

    with pytest.raises(RateLimitExceededError) as caught:
        limiter.acquire_sync(key, limit=ONE)

    assert caught.value.retry_after > 1
    assert sleeps == []


@pytest.mark.asyncio
async def test__acquire__cancelled_while_waiting__keeps_its_slot_reserved(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, key: str
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE, max_wait=math.inf)
    await limiter.acquire(key)
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await limiter.acquire(key)

    assert time.monotonic() - started < 5

    with pytest.raises(RateLimitExceededError) as caught:
        await limiter.acquire(key, max_wait=0)

    assert caught.value.retry_after > 100


def test__acquire_sync__max_wait_argument__overrides_the_limiter(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(max_wait=10)
    limiter.acquire_sync(key, limit=SHORT)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key, limit=SHORT, max_wait=0)


def test__acquire_sync__limiter_key__is_one_shared_bucket(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(key=key, limit=ONE)
    limiter.acquire_sync()

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key)


@pytest.mark.asyncio
async def test__acquire__sync_and_async_limiters__share_one_bucket(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, key: str
) -> None:
    make_limiter(limit=ONE).acquire_sync(key)

    with pytest.raises(RateLimitExceededError):
        await make_limiter(async_redis_client, limit=ONE).acquire(key)


def test__acquire_sync__limit_argument__beats_the_limiter_limit(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(limit=ONE)
    limiter.acquire_sync(key)

    limiter.acquire_sync(key, limit=Limit(2, minutes=1))


def test__acquire_sync__two_limits_on_one_key__count_separately(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter()
    per_second = Limit(1, seconds=1)
    per_hour = Limit(1, hours=1)
    limiter.acquire_sync(key, limit=per_second)

    limiter.acquire_sync(key, limit=per_hour)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key, limit=per_hour)


def test__acquire_sync__three_algorithms_on_one_key__count_separately(
    make_limiter: MakeLimiter, key: str
) -> None:
    for algorithm in (Algorithm.GCRA, Algorithm.FIXED_WINDOW, Algorithm.SLIDING_WINDOW):
        make_limiter(algorithm=algorithm).acquire_sync(key, limit=ONE)


def test__acquire_sync__two_key_prefixes__count_separately(
    redis_client: Redis, prefix: str, key: str
) -> None:
    RateLimiter(redis_client, key_prefix=f'{prefix}:billing').acquire_sync(key, limit=ONE)

    RateLimiter(redis_client, key_prefix=f'{prefix}:search').acquire_sync(key, limit=ONE)


def test__acquire_sync__raw_key__never_reaches_redis(
    limiter: RateLimiter, redis_client: Redis
) -> None:
    client_ip = '203.0.113.7'

    limiter.acquire_sync(client_ip)

    assert list(redis_client.scan_iter(match=f'*{client_ip}*')) == []


def test__acquire_sync__key_with_a_lone_surrogate__is_accepted(limiter: RateLimiter) -> None:
    limiter.acquire_sync('user:\udcff')


def test__acquire_sync__script_not_cached__runs_its_source(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(limit=ONE)
    limiter._script_sha = '0' * 40  # no server has cached a script under it

    limiter.acquire_sync(key)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key)


@pytest.mark.asyncio
async def test__acquire__script_not_cached__runs_its_source(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, key: str
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE)
    limiter._script_sha = '0' * 40  # no server has cached a script under it

    await limiter.acquire(key)

    with pytest.raises(RateLimitExceededError):
        await limiter.acquire(key)


def test__acquire_sync__redis_unreachable__raises_the_redis_error() -> None:
    client = Redis(port=1, socket_connect_timeout=0.5, retry=Retry(NoBackoff(), 0))
    limiter = RateLimiter(client, limit=LONG)

    with pytest.raises(RedisConnectionError):
        limiter.acquire_sync('key')

    client.close()


@pytest.mark.asyncio
async def test__acquire__redis_unreachable__raises_the_redis_error() -> None:
    client = AsyncRedis(port=1, socket_connect_timeout=0.5, retry=Retry(NoBackoff(), 0))
    limiter = RateLimiter(client, limit=LONG)

    with pytest.raises(RedisConnectionError):
        await limiter.acquire('key')

    await client.aclose()


def test__acquire_sync__no_key_anywhere__raises(limiter: RateLimiter) -> None:
    with pytest.raises(ValueError, match='no key'):
        limiter.acquire_sync()


def test__acquire_sync__empty_key__raises(limiter: RateLimiter) -> None:
    with pytest.raises(ValueError, match='key must not be empty'):
        limiter.acquire_sync('')


def test__acquire_sync__no_limit_anywhere__raises(make_limiter: MakeLimiter, key: str) -> None:
    limiter = make_limiter()

    with pytest.raises(ValueError, match='no limit'):
        limiter.acquire_sync(key)


@pytest.mark.parametrize('max_wait', [-1, math.nan])
def test__acquire_sync__invalid_max_wait__raises(
    limiter: RateLimiter, key: str, max_wait: float
) -> None:
    with pytest.raises(ValueError, match='max_wait must be >= 0'):
        limiter.acquire_sync(key, max_wait=max_wait)


@pytest.mark.parametrize(
    ('argument', 'value', 'message'),
    [
        ('key', 42, 'key must be a str, got int'),
        ('limit', 5, 'limit must be a Limit, got int'),
        ('max_wait', True, 'max_wait must be a number of seconds, got bool'),
        ('max_wait', '5', 'max_wait must be a number of seconds, got str'),
    ],
)
def test__acquire_sync__argument_of_the_wrong_type__raises_type_error(
    limiter: RateLimiter, argument: str, value: object, message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        limiter.acquire_sync(**{argument: value})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test__acquire__argument_of_the_wrong_type__raises_type_error(
    async_limiter: RateLimiter,
) -> None:
    with pytest.raises(TypeError, match='key must be a str, got bytes'):
        await async_limiter.acquire(b'user:42')  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test__acquire_sync__async_client__raises_type_error(async_limiter: RateLimiter) -> None:
    with pytest.raises(TypeError, match=r'acquire_sync\(\) needs a redis.Redis client'):
        async_limiter.acquire_sync('key')


@pytest.mark.asyncio
async def test__acquire__sync_client__raises_type_error(limiter: RateLimiter) -> None:
    with pytest.raises(TypeError, match=r'acquire\(\) needs a redis.asyncio.Redis client'):
        await limiter.acquire('key')


def test__rate_limiter__unsupported_client__raises_type_error() -> None:
    with pytest.raises(TypeError, match='got dict'):
        RateLimiter({})  # type: ignore[arg-type]


@pytest.mark.parametrize('option', ['key', 'key_prefix'])
def test__rate_limiter__empty_key_option__raises(redis_client: Redis, option: str) -> None:
    with pytest.raises(ValueError, match=f'{option} must not be empty'):
        RateLimiter(redis_client, **{option: ''})  # type: ignore[arg-type]


@pytest.mark.parametrize('max_wait', [-1, math.nan])
def test__rate_limiter__invalid_max_wait__raises(redis_client: Redis, max_wait: float) -> None:
    with pytest.raises(ValueError, match='max_wait must be >= 0'):
        RateLimiter(redis_client, max_wait=max_wait)


@pytest.mark.parametrize(
    ('option', 'value', 'message'),
    [
        ('key', 42, 'key must be a str, got int'),
        ('key_prefix', b'app', 'key_prefix must be a str, got bytes'),
        ('limit', 5, 'limit must be a Limit, got int'),
        ('max_wait', True, 'max_wait must be a number of seconds, got bool'),
        ('max_wait', None, 'max_wait must be a number of seconds, got NoneType'),
    ],
)
def test__rate_limiter__option_of_the_wrong_type__raises_type_error(
    redis_client: Redis, option: str, value: object, message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        RateLimiter(redis_client, **{option: value})  # type: ignore[arg-type]


def test__rate_limiter__infinite_max_wait__is_accepted(redis_client: Redis) -> None:
    limiter = RateLimiter(redis_client, max_wait=math.inf)

    assert 'max_wait=inf' in repr(limiter)


def test__rate_limiter__algorithm_name__is_accepted(make_limiter: MakeLimiter, key: str) -> None:
    limiter = make_limiter(algorithm='gcra', limit=LONG)

    limiter.acquire_sync(key)


def test__rate_limiter__unknown_algorithm__raises(redis_client: Redis) -> None:
    with pytest.raises(ValueError, match='leaky_bucket'):
        RateLimiter(redis_client, algorithm='leaky_bucket')  # type: ignore[arg-type]


def test__rate_limiter__repr__shows_the_settings(redis_client: Redis) -> None:
    limiter = RateLimiter(redis_client, limit=Limit(5, seconds=1), key='github', max_wait=2)

    assert repr(limiter) == (
        "RateLimiter(limit=Limit(requests=5, seconds=1, minutes=0, hours=0), key='github', "
        "algorithm='fixed_window', max_wait=2.0, key_prefix='ratelimit_io')"
    )
