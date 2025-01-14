import os
import re
import time

import pytest
import redis
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from ratelimit_io import LimitSpec
from ratelimit_io import RatelimitIO


@pytest.fixture(scope="function")
def real_redis_client():
    """
    Real Redis client for synchronous tests.

    This fixture creates a Redis client connected to the host and port specified
    in the environment variables `REDIS_HOST` and `REDIS_PORT`. Before yielding
    the client, all data in Redis is flushed. After the test is complete, the
    client connection is closed.

    Returns:
        Redis: A synchronous Redis client instance.
    """
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))
    client = Redis(host=host, port=port, decode_responses=True)
    client.flushall()
    yield client
    client.close()


@pytest.fixture(scope="function")
async def real_async_redis_client():
    """
    Real Redis client for asynchronous tests.

    This fixture creates an asynchronous Redis client connected to the host and
    port specified in the environment variables `REDIS_HOST` and `REDIS_PORT`.
    Before yielding the client, all data in Redis is flushed. After the test is
    complete, the client connection is closed asynchronously.

    Returns:
        AsyncRedis: An asynchronous Redis client instance.
    """
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))
    client = AsyncRedis(host=host, port=port, decode_responses=True)
    await client.flushall()
    yield client
    await client.aclose()


@pytest.fixture
def limiter(real_redis_client):
    """Fixture for RatelimitIO instance with real Redis."""
    return RatelimitIO(
        backend=real_redis_client,
        base_url="https://api.example.com",
        base_limit=LimitSpec(5, seconds=1),
    )


@pytest.fixture
async def async_limiter(real_async_redis_client):
    """Fixture for RatelimitIO instance with real Redis (async)."""
    return RatelimitIO(
        backend=real_async_redis_client,
        base_url="https://api.example.com",
        base_limit=LimitSpec(5, seconds=1),
    )


def test_sync_limit(limiter):
    """Test synchronous rate limiting."""
    key = "sync_test"

    for _ in range(5):
        limiter.wait(key, LimitSpec(requests=5, seconds=1))

    start_time = time.time()

    limiter.wait(key, LimitSpec(requests=5, seconds=1))

    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time did not occur as expected"


@pytest.mark.asyncio
async def test_async_limit(async_limiter):
    """Test asynchronous rate limiting."""
    key = "async_test"

    await async_limiter.backend.flushall()

    for _ in range(5):
        await async_limiter.a_wait(key, LimitSpec(requests=5, seconds=5))
        await async_limiter.backend.get(async_limiter._generate_key(key))

    start_time = time.time()
    await async_limiter.a_wait(key, LimitSpec(requests=5, seconds=5))
    elapsed_time = time.time() - start_time
    assert elapsed_time >= 0.9, "Wait time did not occur as expected"

    remaining = await async_limiter.backend.get(
        async_limiter._generate_key(key)
    )
    ttl = await async_limiter.backend.ttl(async_limiter._generate_key(key))

    assert remaining is not None, "Key should exist in Redis"
    assert int(remaining) <= 5, f"Unexpected requests count: {remaining}"
    assert ttl > 0, f"Unexpected TTL: {ttl}"


@pytest.mark.asyncio
async def test_async_decorator(async_limiter):
    """Test asynchronous decorator usage."""

    @async_limiter(
        LimitSpec(requests=5, seconds=1), unique_key="async_decorator_test"
    )
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"

    start_time = time.time()
    assert await limited_function() == "success"
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time did not occur as expected"


def test_sync_decorator(limiter):
    """Test synchronous decorator usage."""

    @limiter(
        LimitSpec(requests=5, seconds=1), unique_key="sync_decorator_test"
    )
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    assert limited_function() == "success"
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time did not occur as expected"


@pytest.mark.asyncio
async def test_async_context_manager(async_limiter):
    """Test asynchronous context manager."""
    async with async_limiter:
        await async_limiter.a_wait(
            "context_test", LimitSpec(requests=5, seconds=1)
        )


def test_sync_context_manager(limiter):
    """Test synchronous context manager."""
    with limiter:
        limiter.wait("context_test", LimitSpec(requests=5, seconds=1))


def test_missing_key_and_limit_spec(real_redis_client):
    """Test missing key and limit_spec for `wait`."""
    limiter = RatelimitIO(
        backend=real_redis_client,
        base_url="https://api.example.com",
    )
    with pytest.raises(
        ValueError, match="limit_spec or self.base_limit must be provided"
    ):
        limiter.wait(limit_spec=None)


@pytest.mark.asyncio
async def test_redis_connection_error():
    """Test Redis connection error handling."""
    invalid_client = AsyncRedis(host="localhost", port=12345)
    limiter = RatelimitIO(backend=invalid_client)

    with pytest.raises(redis.exceptions.ConnectionError):
        await limiter.a_wait("unreachable", LimitSpec(5, seconds=1))


def test_invalid_backend_type():
    """Test invalid backend type."""
    with pytest.raises(RuntimeError, match="Unsupported Redis backend"):
        RatelimitIO(backend=None)


def test_key_generation(limiter):
    """Test key generation for consistency."""
    key = limiter._generate_key("test_key")
    assert isinstance(key, str)
    assert len(key) == 64


@pytest.mark.asyncio
async def test_lua_script_loading(async_limiter):
    """Test Lua script loading."""
    await async_limiter._ensure_script_loaded_async()
    exists = await async_limiter.backend.script_exists(
        async_limiter._lua_script_hash
    )
    assert exists[0] is True


@pytest.mark.asyncio
async def test_async_lua_script_not_loaded(
    async_limiter, real_async_redis_client
):
    """Test behavior when Lua script is not loaded (async)."""
    await real_async_redis_client.script_flush()

    await async_limiter.a_wait("test_key", LimitSpec(requests=5, seconds=1))


def test_sync_lua_script_not_loaded(limiter, real_redis_client):
    """Test behavior when Lua script is not loaded (sync)."""
    real_redis_client.script_flush()

    limiter.wait("test_key", LimitSpec(requests=5, seconds=1))


def test_limit_spec_total_seconds():
    """Test all branches of LimitSpec.total_seconds."""
    with pytest.raises(
        ValueError,
        match=re.escape(
            "At least one time frame "
            "(seconds, minutes, or hours) must be provided."
        ),
    ):
        LimitSpec(requests=5)

    with pytest.raises(
        ValueError,
        match=re.escape(
            "At least one time frame "
            "(seconds, minutes, or hours) must be provided."
        ),
    ):
        LimitSpec(requests=5, seconds=0, minutes=0, hours=0)

    # Only seconds
    limit = LimitSpec(requests=5, seconds=30)
    assert limit.total_seconds() == 30

    # Only minutes
    limit = LimitSpec(requests=5, minutes=2)
    assert limit.total_seconds() == 120

    # Only hours
    limit = LimitSpec(requests=5, hours=2)
    assert limit.total_seconds() == 7200

    # Seconds and minutes
    limit = LimitSpec(requests=5, seconds=15, minutes=2)
    assert limit.total_seconds() == 135

    # Seconds and hours
    limit = LimitSpec(requests=5, seconds=15, hours=1)
    assert limit.total_seconds() == 3615

    # Minutes and hours
    limit = LimitSpec(requests=5, minutes=30, hours=1)
    assert limit.total_seconds() == 5400

    # All parameters
    limit = LimitSpec(requests=5, seconds=30, minutes=2, hours=2)
    assert limit.total_seconds() == 7350


def test_limit_spec_str():
    """Test string representation of LimitSpec."""
    limit = LimitSpec(requests=5, seconds=30)
    assert str(limit) == "5/30s"


def test_enforce_limit_sync_noscript_error(limiter, real_redis_client):
    """Test NoScriptError handling in _enforce_limit_sync."""
    limiter.backend.script_flush()
    key = "noscript_test"
    limit = LimitSpec(requests=5, seconds=1)

    assert limiter._enforce_limit_sync(key, limit)


@pytest.mark.asyncio
async def test_enforce_limit_async_noscript_error(
    async_limiter, real_async_redis_client
):
    """Test NoScriptError handling in _enforce_limit_async."""
    await real_async_redis_client.script_flush()
    key = "async_noscript_test"
    limit = LimitSpec(requests=5, seconds=1)

    assert await async_limiter._enforce_limit_async(key, limit)


def test_prepare_key_with_base_url():
    """Test key generation with base_url."""
    limiter = RatelimitIO(
        backend=Redis(decode_responses=True),
        base_url="https://api.example.com",
    )
    limiter.base_limit = LimitSpec(5, seconds=1)

    key, limit_spec = limiter._prepare_key_and_limit(None, None)
    assert key.startswith("outgoing:ratelimit-io:")
    assert limit_spec == limiter.base_limit

    limit_spec = LimitSpec(10, seconds=2)
    key, limit_spec = limiter._prepare_key_and_limit("test_key", limit_spec)
    assert key == "test_key"
    assert limit_spec.requests == 10


def test_ensure_script_loaded_sync(limiter, real_redis_client):
    """Test Lua script loading in _ensure_script_loaded_sync."""
    real_redis_client.script_flush()

    limiter._ensure_script_loaded_sync()


@pytest.mark.asyncio
async def test_ensure_script_loaded_async(
    async_limiter, real_async_redis_client
):
    """Test Lua script loading in _ensure_script_loaded_async."""
    await real_async_redis_client.script_flush()

    await async_limiter._ensure_script_loaded_async()


def test_invalid_prepare_key_and_limit():
    """Test invalid cases for _prepare_key_and_limit."""
    limiter = RatelimitIO(
        backend=Redis(decode_responses=True),
        base_url="https://api.example.com",
    )
    with pytest.raises(
        ValueError, match="limit_spec or self.base_limit must be provided."
    ):
        limiter._prepare_key_and_limit(None, None)


def test_invalid_limit_spec():
    """Test invalid LimitSpec initialization."""
    with pytest.raises(ValueError, match="Requests must be greater than 0."):
        LimitSpec(requests=0)

    with pytest.raises(ValueError, match="At least one time frame"):
        LimitSpec(requests=5)

    with pytest.raises(ValueError, match="At least one time frame"):
        LimitSpec(requests=5, seconds=0, minutes=0, hours=0)


def test_no_script_error_in_enforce_limit_sync(limiter):
    """Test NoScriptError handling for _enforce_limit_sync."""
    limiter.backend.script_flush()
    key = "noscript_test"
    limit = LimitSpec(requests=5, seconds=1)
    assert limiter._enforce_limit_sync(key, limit) is True


@pytest.mark.asyncio
async def test_no_script_error_in_enforce_limit_async(async_limiter):
    """Test NoScriptError handling for _enforce_limit_async."""
    await async_limiter.backend.script_flush()
    key = "noscript_async_test"
    limit = LimitSpec(requests=5, seconds=1)
    assert await async_limiter._enforce_limit_async(key, limit) is True


def test_enforce_limit_sync_failure(limiter):
    """Test _enforce_limit_sync failure case."""
    key = "failure_test"
    limit = LimitSpec(requests=1, seconds=1)

    assert limiter._enforce_limit_sync(key, limit) is True

    assert limiter._enforce_limit_sync(key, limit) is False


@pytest.mark.asyncio
async def test_enforce_limit_async_failure(async_limiter):
    """Test _enforce_limit_async failure case."""
    key = "async_failure_test"
    limit = LimitSpec(requests=1, seconds=1)

    assert await async_limiter._enforce_limit_async(key, limit) is True

    assert not await async_limiter._enforce_limit_async(key, limit)


def test_sync_wrapper_no_exceptions(limiter):
    """Test sync wrapper in the decorator."""

    @limiter(LimitSpec(requests=5, seconds=1), unique_key="sync_wrapper_test")
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"


@pytest.mark.asyncio
async def test_async_wrapper_no_exceptions(async_limiter):
    """Test async wrapper in the decorator."""

    @async_limiter(
        LimitSpec(requests=5, seconds=1), unique_key="async_wrapper_test"
    )
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"


def test_limitspec_invalid_requests():
    """Test LimitSpec raises an error for non-positive requests."""
    with pytest.raises(ValueError, match="Requests must be greater than 0."):
        LimitSpec(requests=0)


def test_limitspec_no_time_frame():
    """Test LimitSpec raises an error when no time frame is provided."""
    with pytest.raises(ValueError, match="At least one time frame"):
        LimitSpec(requests=5, seconds=0, minutes=0, hours=0)
