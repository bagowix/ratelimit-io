"""Redis clients, limiters and keys shared by the suite.

By default every test runs against in-process ``fakeredis`` (Lua-capable), so
``uv run pytest`` needs no server. Set ``RATELIMIT_IO_TEST_REDIS_URL`` to run the
same tests against a real server, Redis or Valkey; CI does both. Tests marked
``requires_real_redis`` prove atomicity under concurrency, which only a real
server can show, and are skipped on ``fakeredis``.

Each test gets its own ``key_prefix`` and deletes its keys afterwards, never
flushing: a real server may be shared by xdist workers, by runs repeated
within a minute, or by other projects.
"""

import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator

import fakeredis
import pytest
import pytest_asyncio
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from ratelimit_io import Algorithm, Limit, RateLimiter

REDIS_URL = os.environ.get('RATELIMIT_IO_TEST_REDIS_URL')

# One in-process server behind the sync and the async fake clients, as a real
# server is behind real ones.
FAKE_SERVER = fakeredis.FakeServer()

requires_real_redis = pytest.mark.skipif(
    REDIS_URL is None,
    reason='atomicity is verified only against a real server (set RATELIMIT_IO_TEST_REDIS_URL)',
)

ALGORITHMS = tuple(Algorithm)

# Long enough that no test sees a window end by accident.
LONG = Limit(3, minutes=1)

MakeLimiter = Callable[..., RateLimiter]


@pytest.fixture(scope='session')
def redis_client() -> Iterator[Redis]:
    # One client for the whole session: the fakeredis Lua runtime is expensive
    # to spin up, and tests isolate by key prefix rather than by connection.
    client = (
        fakeredis.FakeRedis(server=FAKE_SERVER) if REDIS_URL is None else Redis.from_url(REDIS_URL)
    )

    yield client

    client.close()


@pytest_asyncio.fixture
async def async_redis_client() -> AsyncIterator[AsyncRedis]:
    client = (
        fakeredis.FakeAsyncRedis(server=FAKE_SERVER)
        if REDIS_URL is None
        else AsyncRedis.from_url(REDIS_URL)
    )

    yield client

    await client.aclose()


@pytest.fixture
def prefix(redis_client: Redis) -> Iterator[str]:
    prefix = f'ratelimit_io_test:{uuid.uuid4().hex}'

    yield prefix

    stale = list(redis_client.scan_iter(match=f'{prefix}:*'))
    if stale:
        redis_client.delete(*stale)


@pytest.fixture
def make_limiter(redis_client: Redis, prefix: str) -> MakeLimiter:
    """Build a limiter under the test's own prefix, on the sync client by default."""

    def make(client: Redis | AsyncRedis | None = None, **options: object) -> RateLimiter:
        chosen = redis_client if client is None else client

        return RateLimiter(chosen, key_prefix=prefix, **options)  # type: ignore[arg-type]

    return make


@pytest.fixture
def key() -> str:
    return f'key:{uuid.uuid4().hex}'


@pytest.fixture(params=ALGORITHMS)
def algorithm(request: pytest.FixtureRequest) -> Algorithm:
    return Algorithm(request.param)


@pytest.fixture
def limiter(make_limiter: MakeLimiter, algorithm: Algorithm) -> RateLimiter:
    return make_limiter(limit=LONG, algorithm=algorithm)


@pytest.fixture
def async_limiter(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, algorithm: Algorithm
) -> RateLimiter:
    return make_limiter(async_redis_client, limit=LONG, algorithm=algorithm)


def bucket_of(limiter: RateLimiter, key: str, limit: Limit) -> str:
    """Return the Redis key that holds the bucket of ``key`` under ``limit``."""
    return limiter._bucket(key, limit)
