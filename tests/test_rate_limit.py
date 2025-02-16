import os
import re
import time
from typing import AsyncGenerator
from typing import Generator
from unittest.mock import patch

import pytest
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from ratelimit_io import LimitSpec
from ratelimit_io import RatelimitExceededError
from ratelimit_io import RatelimitIO
from ratelimit_io import RatelimitIOError
from ratelimit_io import ScriptLoadError


@pytest.fixture(scope="function")
def real_redis_client() -> Generator[Redis, None, None]:
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
async def real_async_redis_client() -> AsyncGenerator[AsyncRedis, None]:
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
    await client.aclose()  # type: ignore


@pytest.fixture
def limiter(real_redis_client) -> RatelimitIO:
    """Fixture for RatelimitIO instance with real Redis."""
    return RatelimitIO(
        backend=real_redis_client,
        default_limit=LimitSpec(5, seconds=1),
    )


@pytest.fixture
async def async_limiter(real_async_redis_client) -> RatelimitIO:
    """Fixture for RatelimitIO instance with real Redis (async)."""
    return RatelimitIO(
        backend=real_async_redis_client,
        default_limit=LimitSpec(5, seconds=1),
    )


def test_sync_limit_incoming(limiter) -> None:
    """Test synchronous rate limiting with is_incoming=True."""
    limiter.is_incoming = True
    key = "sync_incoming_test"

    for _ in range(5):
        limiter.wait(key, LimitSpec(requests=5, seconds=1))

    with pytest.raises(RatelimitExceededError, match="Too many requests"):
        limiter.wait(key, LimitSpec(requests=5, seconds=1))


@pytest.mark.asyncio
async def test_async_limit_incoming(async_limiter) -> None:
    """Test asynchronous rate limiting with is_incoming=True."""
    async_limiter.is_incoming = True
    key = "async_incoming_test"

    for _ in range(5):
        await async_limiter.a_wait(key, LimitSpec(requests=5, seconds=1))

    with pytest.raises(RatelimitIOError, match="Too many requests"):
        await async_limiter.a_wait(key, LimitSpec(requests=5, seconds=1))


@pytest.mark.asyncio
async def test_async_decorator_incoming(async_limiter) -> None:
    """Test asynchronous decorator usage with is_incoming=True."""
    async_limiter.is_incoming = True

    @async_limiter(
        LimitSpec(requests=5, seconds=1), unique_key="async_test_key"
    )
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"

    with pytest.raises(RatelimitExceededError, match="Too many requests"):
        await limited_function()


def test_sync_decorator_incoming(limiter) -> None:
    """Test synchronous decorator usage with is_incoming=True."""
    limiter.is_incoming = True

    @limiter(
        limit_spec=LimitSpec(requests=5, seconds=1), unique_key="sync_test_key"
    )
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    with pytest.raises(RatelimitIOError, match="Too many requests"):
        limited_function()


def test_sync_limit_outgoing(limiter) -> None:
    """Test synchronous rate limiting with is_incoming=False."""
    limiter.is_incoming = False
    key = "sync_outgoing_test"

    for _ in range(5):
        limiter.wait(key, LimitSpec(requests=5, seconds=1))

    start_time = time.time()
    limiter.wait(key, LimitSpec(requests=5, seconds=1))
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied for outgoing request"


@pytest.mark.asyncio
async def test_async_limit_outgoing(async_limiter) -> None:
    """Test asynchronous rate limiting with is_incoming=False."""
    async_limiter.is_incoming = False
    key = "async_outgoing_test"

    for _ in range(5):
        await async_limiter.a_wait(key, LimitSpec(requests=5, seconds=1))

    start_time = time.time()
    await async_limiter.a_wait(key, LimitSpec(requests=5, seconds=1))
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied for outgoing request"


def test_default_key_incoming_behavior(limiter) -> None:
    """Test default_key behavior when is_incoming=True."""
    limiter.is_incoming = True
    limiter.default_key = "default_key_incoming"

    @limiter
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    with pytest.raises(RatelimitIOError, match="Too many requests"):
        limited_function()


@pytest.mark.asyncio
async def test_default_key_incoming_behavior_async(async_limiter) -> None:
    """Test default_key behavior when is_incoming=True (async)."""
    async_limiter.is_incoming = True
    async_limiter.default_key = "default_async_key"

    @async_limiter
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"

    with pytest.raises(RatelimitIOError, match="Too many requests"):
        await limited_function()


def test_sync_decorator_without_args(limiter) -> None:
    """Test synchronous decorator without arguments."""
    limiter.is_incoming = False
    limiter.default_key = "default_test_key"

    @limiter
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied with default_key"


@pytest.mark.asyncio
async def test_async_decorator_without_args(async_limiter) -> None:
    """Test asynchronous decorator without arguments."""
    async_limiter.is_incoming = False
    async_limiter.default_key = "default_async_key"

    @async_limiter
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"

    start_time = time.time()
    await limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied with default_key"


def test_missing_key_and_limit_spec(real_redis_client) -> None:
    """Test missing key and limit_spec for `wait`."""
    limiter = RatelimitIO(
        backend=real_redis_client,
    )
    with pytest.raises(
        ValueError, match="limit_spec or self.default_limit must be provided"
    ):
        limiter.wait(limit_spec=None)


@pytest.mark.asyncio
async def test_redis_connection_error() -> None:
    """Test Redis connection error handling."""
    invalid_client = AsyncRedis(host="localhost", port=12345)
    limiter = RatelimitIO(backend=invalid_client)

    with pytest.raises(ScriptLoadError):
        await limiter.a_wait("unreachable", LimitSpec(5, seconds=1))


def test_invalid_backend_type() -> None:
    """Test invalid backend type."""
    with pytest.raises(RuntimeError, match="Unsupported Redis backend"):
        RatelimitIO(backend=None)  # type: ignore[arg-type]


def test_key_generation(limiter) -> None:
    """Test key generation for consistency."""
    key = limiter._generate_key("test_key")
    assert isinstance(key, str)
    assert len(key) == 64


@pytest.mark.asyncio
async def test_lua_script_loading(async_limiter) -> None:
    """Test Lua script loading."""
    await async_limiter._ensure_script_loaded_async()
    exists = await async_limiter.backend.script_exists(
        async_limiter._lua_script_hash
    )
    assert exists[0] is True


@pytest.mark.asyncio
async def test_async_lua_script_not_loaded(
    async_limiter, real_async_redis_client
) -> None:
    """Test behavior when Lua script is not loaded (async)."""
    await real_async_redis_client.script_flush()

    await async_limiter.a_wait("test_key", LimitSpec(requests=5, seconds=1))


def test_sync_lua_script_not_loaded(limiter, real_redis_client) -> None:
    """Test behavior when Lua script is not loaded (sync)."""
    real_redis_client.script_flush()

    limiter.wait("test_key", LimitSpec(requests=5, seconds=1))


def test_limit_spec_total_seconds() -> None:
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


def test_limit_spec_str() -> None:
    """Test string representation of LimitSpec."""
    limit = LimitSpec(requests=5, seconds=30)
    assert str(limit) == "5/30s"


def test_enforce_limit_sync_noscript_error(limiter, real_redis_client) -> None:
    """Test NoScriptError handling in _enforce_limit_sync."""
    limiter.backend.script_flush()
    key = "noscript_test"
    limit = LimitSpec(requests=5, seconds=1)

    assert limiter._enforce_limit_sync(key, limit)


@pytest.mark.asyncio
async def test_enforce_limit_async_noscript_error(
    async_limiter, real_async_redis_client
) -> None:
    """Test NoScriptError handling in _enforce_limit_async."""
    await real_async_redis_client.script_flush()
    key = "async_noscript_test"
    limit = LimitSpec(requests=5, seconds=1)

    assert await async_limiter._enforce_limit_async(key, limit)


def test_prepare_key_with_base_url() -> None:
    """Test key generation with base_url."""
    limiter = RatelimitIO(
        backend=Redis(decode_responses=True),
    )
    limiter.default_limit = LimitSpec(5, seconds=1)

    key = limiter._prepare_key(None)
    assert key.startswith("unknown_key")
    assert limiter.default_limit.requests == 5


def test_ensure_script_loaded_sync(limiter, real_redis_client) -> None:
    """Test Lua script loading in _ensure_script_loaded_sync."""
    real_redis_client.script_flush()

    limiter._ensure_script_loaded_sync()


@pytest.mark.asyncio
async def test_ensure_script_loaded_async(
    async_limiter, real_async_redis_client
) -> None:
    """Test Lua script loading in _ensure_script_loaded_async."""
    await real_async_redis_client.script_flush()

    await async_limiter._ensure_script_loaded_async()


def test_invalid_limit_spec() -> None:
    """Test invalid LimitSpec initialization."""
    with pytest.raises(ValueError, match="Requests must be greater than 0."):
        LimitSpec(requests=0)

    with pytest.raises(ValueError, match="At least one time frame"):
        LimitSpec(requests=5)

    with pytest.raises(ValueError, match="At least one time frame"):
        LimitSpec(requests=5, seconds=0, minutes=0, hours=0)


def test_no_script_error_in_enforce_limit_sync(limiter) -> None:
    """Test NoScriptError handling for _enforce_limit_sync."""
    limiter.backend.script_flush()
    key = "noscript_test"
    limit = LimitSpec(requests=5, seconds=1)
    assert limiter._enforce_limit_sync(key, limit) is True


@pytest.mark.asyncio
async def test_no_script_error_in_enforce_limit_async(async_limiter) -> None:
    """Test NoScriptError handling for _enforce_limit_async."""
    await async_limiter.backend.script_flush()
    key = "noscript_async_test"
    limit = LimitSpec(requests=5, seconds=1)
    assert await async_limiter._enforce_limit_async(key, limit) is True


def test_enforce_limit_sync_failure(limiter) -> None:
    """Test _enforce_limit_sync failure case."""
    key = "failure_test"
    limit = LimitSpec(requests=1, seconds=1)

    assert limiter._enforce_limit_sync(key, limit) is True

    assert limiter._enforce_limit_sync(key, limit) is False


@pytest.mark.asyncio
async def test_enforce_limit_async_failure(async_limiter) -> None:
    """Test _enforce_limit_async failure case."""
    key = "async_failure_test"
    limit = LimitSpec(requests=1, seconds=1)

    assert await async_limiter._enforce_limit_async(key, limit) is True

    assert not await async_limiter._enforce_limit_async(key, limit)


def test_sync_wrapper_no_exceptions(limiter) -> None:
    """Test sync wrapper in the decorator."""

    @limiter(LimitSpec(requests=5, seconds=1), unique_key="sync_wrapper_test")
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"


@pytest.mark.asyncio
async def test_async_wrapper_no_exceptions(async_limiter) -> None:
    """Test async wrapper in the decorator."""

    @async_limiter(
        LimitSpec(requests=5, seconds=1), unique_key="async_wrapper_test"
    )
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"


def test_limitspec_invalid_requests() -> None:
    """Test LimitSpec raises an error for non-positive requests."""
    with pytest.raises(ValueError, match="Requests must be greater than 0."):
        LimitSpec(requests=0)


def test_limitspec_no_time_frame() -> None:
    """Test LimitSpec raises an error when no time frame is provided."""
    with pytest.raises(ValueError, match="At least one time frame"):
        LimitSpec(requests=5, seconds=0, minutes=0, hours=0)


def test_default_key_usage(limiter) -> None:
    """Test the usage of default_key when unique_key is not provided."""
    limiter.is_incoming = False
    limiter.default_key = "default_test_key"

    @limiter
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied with default_key"


def test_override_default_key(limiter) -> None:
    """Test overriding default_key with unique_key."""
    limiter.is_incoming = False
    limiter.default_key = "default_test_key"

    @limiter(
        limit_spec=LimitSpec(requests=3, seconds=2), unique_key="custom_key"
    )
    def limited_function():
        return "success"

    for _ in range(3):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 1.9, "Wait time not applied with custom unique_key"


def test_priority_unique_key_over_default_key(limiter) -> None:
    """Test that unique_key takes precedence over default_key."""
    limiter.is_incoming = False
    limiter.default_key = "default_test_key"

    @limiter(
        limit_spec=LimitSpec(requests=5, seconds=1), unique_key="priority_key"
    )
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied with unique_key"


def test_priority_default_key_over_ip(limiter) -> None:
    """Test that default_key takes precedence over ip from kwargs."""
    limiter.is_incoming = False
    limiter.default_key = "default_test_key"

    @limiter
    def limited_function(ip="user_ip"):
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function(ip="ignored_ip")
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied with default_key"


def test_ip_key_as_fallback(limiter) -> None:
    """Test that ip from kwargs is used if no other keys are provided."""
    limiter.is_incoming = False
    limiter.default_key = None

    @limiter
    def limited_function(ip="user_ip"):
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied with ip key"


def test_call_decorator_no_limit_spec_or_default_limit() -> None:
    """Test decorator raises ValueError if no limit_spec or default_limit."""
    limiter = RatelimitIO(backend=Redis(decode_responses=True))
    with pytest.raises(
        ValueError, match="Rate limit specification is missing"
    ):

        @limiter
        def func():
            pass


def test_override_is_incoming_false_sync(limiter) -> None:
    """Test overriding is_incoming=False for sync decorators."""
    limiter.is_incoming = False

    @limiter
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"

    start_time = time.time()
    limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied for outgoing requests"


@pytest.mark.asyncio
async def test_override_is_incoming_false_async(async_limiter) -> None:
    """Test overriding is_incoming=False for async decorators."""
    async_limiter.is_incoming = False

    @async_limiter
    async def limited_function():
        return "success"

    for _ in range(5):
        assert await limited_function() == "success"

    start_time = time.time()
    await limited_function()
    elapsed_time = time.time() - start_time

    assert elapsed_time >= 0.9, "Wait time not applied for outgoing requests"


def test_ratelimit_exceeded_error() -> None:
    """Test the RatelimitExceededError exception properties."""
    error = RatelimitExceededError()
    assert error.detail == "Too many requests"
    assert error.status_code == 429


@pytest.mark.asyncio
async def test_async_wrapper_ratelimit_exceeded(async_limiter) -> None:
    """
    Test that the async decorator raises an error when rate limit is exceeded.
    """

    @async_limiter(limit_spec=LimitSpec(1, seconds=1))
    async def limited_function():
        return "success"

    await limited_function()
    with pytest.raises(RatelimitIOError):
        await limited_function()


def test_wait_ratelimit_exceeded(limiter) -> None:
    """
    Test that the sync `wait` method raises an error
        when rate limit is exceeded.
    """
    limiter.wait(
        key="test_key", limit_spec=LimitSpec(1, seconds=1), max_wait_time=0.1
    )

    with pytest.raises(RatelimitExceededError):
        limiter.wait(
            key="test_key",
            limit_spec=LimitSpec(1, seconds=1),
            max_wait_time=0.1,
        )


@pytest.mark.asyncio
async def test_a_wait_ratelimit_exceeded(async_limiter) -> None:
    """
    Test that the async `a_wait` method raises
        an error when rate limit is exceeded.
    """
    await async_limiter.a_wait(
        key="test_key", limit_spec=LimitSpec(1, seconds=1), max_wait_time=0.1
    )

    with pytest.raises(RatelimitExceededError):
        await async_limiter.a_wait(
            key="test_key",
            limit_spec=LimitSpec(1, seconds=1),
            max_wait_time=0.1,
        )


def test_enforce_limit_sync_script_load_error(
    limiter, real_redis_client
) -> None:
    """
    Test that the sync `_enforce_limit_sync`
        raises ScriptLoadError if the script fails to load.
    """
    real_redis_client.script_flush()

    limiter.backend = real_redis_client
    with pytest.raises(ScriptLoadError), patch(
        "ratelimit_io.rate_limit.RatelimitIO._ensure_script_loaded_sync"
    ):
        limiter._enforce_limit_sync("test_key", LimitSpec(1, seconds=1))


@pytest.mark.asyncio
async def test_enforce_limit_async_script_load_error(
    async_limiter, real_async_redis_client
) -> None:
    """
    Test that the async `_enforce_limit_async`
        raises ScriptLoadError if the script fails to load.
    """
    await real_async_redis_client.script_flush()

    async_limiter.backend = real_async_redis_client
    with pytest.raises(ScriptLoadError), patch(
        "ratelimit_io.rate_limit.RatelimitIO._ensure_script_loaded_async"
    ):
        await async_limiter._enforce_limit_async(
            "test_key", LimitSpec(1, seconds=1)
        )


def test_missing_limit_spec_or_default_limit() -> None:
    """
    Test that `wait` raises ValueError
        when neither limit_spec nor default_limit is provided.
    """
    limiter = RatelimitIO(backend=Redis(decode_responses=True))
    with pytest.raises(
        ValueError, match="limit_spec or self.default_limit must be provided"
    ):
        limiter.wait(key="test_key", limit_spec=None)


def test_sync_wrapper_decorator(limiter) -> None:
    """
    Test the sync decorator wrapper applies rate limiting correctly.
    """

    @limiter(
        limit_spec=LimitSpec(requests=5, seconds=1),
        unique_key="sync_wrapper_test",
    )
    def limited_function():
        return "success"

    for _ in range(5):
        assert limited_function() == "success"


@pytest.mark.asyncio
async def test_async_wait_branch(async_limiter) -> None:
    """
    Test the async `a_wait` method handles rate limit enforcement correctly.
    """
    await async_limiter.a_wait(
        key="test_key", limit_spec=LimitSpec(1, seconds=1), max_wait_time=0.1
    )
    with pytest.raises(RatelimitExceededError):
        await async_limiter.a_wait(
            key="test_key",
            limit_spec=LimitSpec(1, seconds=1),
            max_wait_time=0.1,
        )


def test_ensure_script_loaded_sync_error(limiter, real_redis_client) -> None:
    """
    Test that `_ensure_script_loaded_sync`
        raises ScriptLoadError if the script fails to load.
    """
    real_redis_client.script_flush()
    limiter.backend = real_redis_client
    with pytest.raises(ScriptLoadError), patch(
        "redis.commands.core.ScriptCommands.script_load",
        side_effect=Exception("mock error"),
    ):
        limiter._ensure_script_loaded_sync()


@pytest.mark.asyncio
async def test_async_context_manager_lua_script_loading(
    real_async_redis_client,
) -> None:
    """
    Test that Lua script is loaded correctly when using the async context manager.
    """
    async with RatelimitIO(backend=real_async_redis_client) as limiter:
        script_exists = await real_async_redis_client.script_exists(
            limiter._lua_script_hash
        )
        assert script_exists[0], "Lua script was not loaded in context manager"

        await limiter.a_wait("test_key", LimitSpec(1, seconds=1))


@pytest.mark.asyncio
async def test_async_context_manager_no_errors_on_exit(
    real_async_redis_client,
) -> None:
    """
    Test that the async context manager exits gracefully without errors.
    """
    async with RatelimitIO(backend=real_async_redis_client) as limiter:
        await limiter.a_wait("test_key", LimitSpec(1, seconds=1))

    assert True, "Async context manager raised an unexpected exception on exit"


@pytest.mark.asyncio
async def test_async_context_manager_reuse() -> None:
    """
    Test reusing the same RatelimitIO instance in different contexts.
    """
    redis_client = AsyncRedis(
        host="localhost", port=6379, decode_responses=True
    )
    limiter = RatelimitIO(backend=redis_client)

    async with limiter:
        await limiter.a_wait("test_key_1", LimitSpec(1, seconds=1))

    async with limiter:
        await limiter.a_wait("test_key_2", LimitSpec(1, seconds=1))

    assert redis_client.ping(), "Redis connection was closed unexpectedly"
    await redis_client.aclose()  # type: ignore[attr-defined]
