import time
from typing import Callable
from typing import Optional
from typing import Tuple
from typing import Union

import asyncio
import hashlib
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import NoScriptError
from typing_extensions import TypeAlias


class RatelimitIOError(Exception):
    """Raised when the rate limit is exceeded."""


class LimitSpec:
    """
    Specifies the number of requests allowed in a time frame.

    Attributes:
        requests (int): Maximum number of requests.
        seconds (Optional[int]): Time frame in seconds.
        minutes (Optional[int]): Time frame in minutes.
        hours (Optional[int]): Time frame in hours.
    """

    def __init__(
        self,
        requests: int,
        seconds: Optional[int] = None,
        minutes: Optional[int] = None,
        hours: Optional[int] = None,
    ):
        if requests <= 0:
            raise ValueError("Requests must be greater than 0.")

        self.requests = requests
        self.seconds = seconds
        self.minutes = minutes
        self.hours = hours

        if self.total_seconds() == 0:
            raise ValueError(
                "At least one time frame "
                "(seconds, minutes, or hours) must be provided."
            )

    def total_seconds(self) -> int:
        """
        Calculates the total time frame in seconds.

        Returns:
            int: Total time in seconds.
        """
        total = 0
        if self.seconds:
            total += self.seconds
        if self.minutes:
            total += self.minutes * 60
        if self.hours:
            total += self.hours * 3600
        return total

    def __str__(self) -> str:
        return f"{self.requests}/{self.total_seconds()}s"


RedisBackend: TypeAlias = Union[Redis, AsyncRedis]


class RatelimitIO:
    """Rate limiter for managing incoming and outgoing request limits."""

    def __init__(
        self,
        backend: RedisBackend,
        base_url: Optional[str] = None,
        base_limit: Optional[LimitSpec] = None,
    ):
        """
        Initializes the RatelimitIO instance.

        Args:
            backend (Redis | AsyncRedis): Redis backend instance.
            base_url (Optional[str]): Base URL for outgoing request limits.
            base_limit (Optional[LimitSpec]): Default rate
                limit for the base URL.
        """
        if not isinstance(backend, (Redis, AsyncRedis)):
            raise RuntimeError("Unsupported Redis backend.")

        self.backend = backend
        self.base_url = base_url
        self.base_limit = base_limit

        self._lua_script = b"""
            local current = redis.call("GET", KEYS[1])
            local limit = tonumber(ARGV[1])
            local ttl = tonumber(ARGV[2])

            if current and tonumber(current) >= limit then
                return 0
            else
                local new_count = redis.call("INCR", KEYS[1])
                if new_count == 1 then
                    redis.call("EXPIRE", KEYS[1], ttl)
                end
                return 1
            end
        """
        self._lua_script_hash = hashlib.sha1(self._lua_script).hexdigest()
        self._script_loaded = False

    def __call__(
        self, limit_spec: LimitSpec, unique_key: Optional[str] = None
    ) -> Callable:
        """
        Decorator for applying rate limits to functions.

        Args:
            limit_spec (LimitSpec): Rate limit specification.
            unique_key (Optional[str]): Optional unique key for rate limiting.

        Returns:
            Callable: Decorated function.
        """

        def decorator(func: Callable) -> Callable:
            async def async_wrapper(*args, **kwargs):
                key = unique_key or kwargs.get("ip", "unknown_ip")
                try:
                    await self.a_wait(f"incoming:{key}", limit_spec)
                except RatelimitIOError as exc:
                    raise RuntimeError(
                        f"Rate limit exceeded in {func.__name__}: {str(exc)}"
                    ) from exc
                return await func(*args, **kwargs)

            def sync_wrapper(*args, **kwargs):
                key = unique_key or kwargs.get("ip", "unknown_ip")
                try:
                    self.wait(f"incoming:{key}", limit_spec)
                except RatelimitIOError as exc:
                    raise RuntimeError(
                        f"Rate limit exceeded in {func.__name__}: {str(exc)}"
                    ) from exc
                return func(*args, **kwargs)

            return (
                async_wrapper
                if asyncio.iscoroutinefunction(func)
                else sync_wrapper
            )

        return decorator

    def __enter__(self) -> "RatelimitIO":
        """Synchronous context manager."""
        self._ensure_script_loaded_sync()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """No cleanup is necessary for this context manager."""
        pass

    async def __aenter__(self) -> "RatelimitIO":
        """Context manager for async operations."""
        await self._ensure_script_loaded_async()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """No cleanup is necessary for this context manager."""
        pass

    def wait(
        self,
        key: Optional[str] = None,
        limit_spec: Optional[LimitSpec] = None,
        max_wait_time: float = 10.0,
        backoff_start: float = 0.01,
        backoff_max: float = 0.1,
    ) -> None:
        """
        Synchronous rate limiting. Waits if the limit is exceeded.

        Args:
            key (Optional[str]): Unique identifier for the rate limit.
                Defaults to `base_url`.
            limit_spec (Optional[LimitSpec]): Rate specification.
                Defaults to `base_limit`.
            max_wait_time (float): Maximum wait time in seconds
                before raising an error.
            backoff_start (float): Initial backoff delay in seconds.
            backoff_max (float): Maximum backoff delay in seconds.

        Raises:
            RatelimitIOError: If the rate limit is exceeded and
                max wait time is reached.
        """
        self._ensure_script_loaded_sync()

        key, limit_spec = self._prepare_key_and_limit(key, limit_spec)
        start_time = time.time()
        backoff = backoff_start

        while not self._enforce_limit_sync(key, limit_spec):
            if time.time() - start_time > max_wait_time:
                raise RatelimitIOError(
                    f"Rate limit exceeded for {key}, wait time exceeded."
                )
            time.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)

    async def a_wait(
        self,
        key: Optional[str] = None,
        limit_spec: Optional[LimitSpec] = None,
        max_wait_time: float = 10.0,
        backoff_start: float = 0.01,
        backoff_max: float = 0.1,
    ) -> None:
        """
        Asynchronous rate limiting. Waits if the limit is exceeded.

        Args:
            key (Optional[str]): Unique identifier for the rate limit.
                Defaults to `base_url`.
            limit_spec (Optional[LimitSpec]): Rate specification.
                Defaults to `base_limit`.
            max_wait_time (float): Maximum wait time in seconds
                before raising an error.
            backoff_start (float): Initial backoff delay in seconds.
            backoff_max (float): Maximum backoff delay in seconds.

        Raises:
            RatelimitIOError: If the rate limit is exceeded and
                max wait time is reached.
        """
        await self._ensure_script_loaded_async()

        key, limit_spec = self._prepare_key_and_limit(key, limit_spec)
        start_time = time.time()
        backoff = backoff_start

        while not await self._enforce_limit_async(key, limit_spec):
            if time.time() - start_time > max_wait_time:
                raise RatelimitIOError(
                    f"Rate limit exceeded for {key}, wait time exceeded."
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)

    def _prepare_key_and_limit(
        self, key: Optional[str] = None, limit_spec: Optional[LimitSpec] = None
    ) -> Tuple[str, LimitSpec]:
        """
        Prepares the key and limit specification, falling back to
            defaults if needed.

        Args:
            key (Optional[str]): Unique identifier for the rate limit.
            limit_spec (Optional[LimitSpec]): Limit specification.

        Returns:
            tuple[str, LimitSpec]: Prepared key and rate specification.

        Raises:
            ValueError: If neither key nor base settings are provided.
        """
        if not (limit_spec or self.base_limit):
            raise ValueError("limit_spec or self.base_limit must be provided.")

        requests_for_key: str = (
            str(limit_spec.requests)
            if limit_spec
            else str(self.base_limit.requests)  # type: ignore
        )
        time_for_key: str = (
            str(limit_spec.total_seconds())
            if limit_spec
            else str(self.base_limit.total_seconds())  # type: ignore
        )

        key = key or (
            f"outgoing:ratelimit-io:{self.base_url}:"
            f"requests:{requests_for_key}:"
            f"time:{time_for_key}"
        )
        limit_spec = limit_spec or self.base_limit

        if not key or not limit_spec:
            raise ValueError("Key and limit_spec must be provided.")
        return key, limit_spec

    def _enforce_limit_sync(self, key: str, limit_spec: LimitSpec) -> bool:
        """
        Enforces the rate limit synchronously.

        Args:
            key (str): Unique identifier for the rate limit.
            limit_spec (LimitSpec): Limit specification.

        Returns:
            bool: True if the request is allowed, False otherwise.
        """
        try:
            allowed = self.backend.evalsha(
                self._lua_script_hash,
                1,
                self._generate_key(key),
                str(limit_spec.requests),
                str(limit_spec.total_seconds()),
            )
            return bool(allowed)
        except NoScriptError:
            self._ensure_script_loaded_sync()
            try:
                allowed = self.backend.evalsha(
                    self._lua_script_hash,
                    1,
                    self._generate_key(key),
                    str(limit_spec.requests),
                    str(limit_spec.total_seconds()),
                )
                return bool(allowed)
            except NoScriptError as exc:
                raise RuntimeError(
                    "Failed to load Lua script into Redis."
                ) from exc

    async def _enforce_limit_async(
        self, key: str, limit_spec: LimitSpec
    ) -> bool:
        """
        Enforces the rate limit asynchronously.

        Args:
            key (str): Unique identifier for the rate limit.
            limit_spec (LimitSpec): Limit specification.

        Returns:
            bool: True if the request is allowed, False otherwise.
        """
        try:
            allowed = await self.backend.evalsha(
                self._lua_script_hash,
                1,
                self._generate_key(key),
                str(limit_spec.requests),
                str(limit_spec.total_seconds()),
            )
            return bool(allowed)
        except NoScriptError:
            # Attempt to load the script and retry once
            await self._ensure_script_loaded_async()
            try:
                allowed = await self.backend.evalsha(
                    self._lua_script_hash,
                    1,
                    self._generate_key(key),
                    str(limit_spec.requests),
                    str(limit_spec.total_seconds()),
                )
                return bool(allowed)
            except NoScriptError as exc:
                # If script loading fails again, raise an error
                raise RuntimeError(
                    "Failed to load Lua script into Redis."
                ) from exc

    def _generate_key(self, identifier: str) -> str:
        """
        Generates a unique Redis key for rate limiting.

        Args:
            identifier (str): Unique identifier for the rate limit.

        Returns:
            str: Hashed Redis key.
        """
        return hashlib.sha256(identifier.encode("utf-8")).hexdigest()

    def _ensure_script_loaded_sync(self) -> None:
        """Ensures the Lua script is loaded into Redis (synchronously)."""
        if not self.backend.script_exists(self._lua_script_hash)[0]:
            self.backend.script_load(self._lua_script)
        self._script_loaded = True

    async def _ensure_script_loaded_async(self) -> None:
        """Ensures the Lua script is loaded into Redis (asynchronously)."""
        if not (await self.backend.script_exists(self._lua_script_hash))[0]:
            await self.backend.script_load(self._lua_script)
        self._script_loaded = True
