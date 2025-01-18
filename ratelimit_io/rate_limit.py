import logging
import time
from functools import wraps
from types import TracebackType
from typing import Callable
from typing import Optional
from typing import Type
from typing import Union

import asyncio
import hashlib
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import NoScriptError

logger = logging.getLogger(__name__)


class RatelimitIOError(Exception):
    """Base class for all rate limit errors."""

    def __init__(
        self,
        detail: Optional[str] = "Too many Requests",
        status_code: Optional[int] = 429,
    ) -> None:
        """
        Initializes the RatelimitIOError instance.

        Args:
            detail (Optional[str]): Error detail message.
            status_code (Optional[int]): HTTP status code.
        """
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class RatelimitExceededError(RatelimitIOError):
    """Raised when the rate limit is exceeded."""

    def __init__(
        self,
        detail: Optional[str] = "Too many requests",
        status_code: Optional[int] = 429,
    ) -> None:
        """
        Initializes the RatelimitExceededError instance.

        Args:
            detail (Optional[str]): Error detail message.
            status_code (Optional[int]): HTTP status code.
        """
        super().__init__(detail, status_code)


class ScriptLoadError(RatelimitIOError):
    """Raised when the Lua script fails to load into Redis."""

    def __init__(
        self,
        detail: Optional[str] = "Failed to load Lua script into Redis.",
        status_code: Optional[int] = 500,
    ) -> None:
        """
        Initializes the ScriptLoadError instance.

        Args:
            detail (Optional[str]): Error detail message.
            status_code (Optional[int]): HTTP status code.
        """
        super().__init__(detail, status_code)


class LimitSpec:
    """Specifies the number of requests allowed in a time frame."""

    def __init__(
        self,
        requests: int,
        seconds: Optional[int] = None,
        minutes: Optional[int] = None,
        hours: Optional[int] = None,
    ) -> None:
        """
        Initializes the LimitSpec instance.

        Args:
            requests (int): Maximum number of requests.
            seconds (Optional[int]): Time frame in seconds.
            minutes (Optional[int]): Time frame in minutes.
            hours (Optional[int]): Time frame in hours.

        Raises:
            ValueError: If requests <= 0 or no time frame is provided.
        """
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
        """
        Returns a string representation of the limit specification.

        Returns:
            str: String representation of the limit specification.
        """
        return f"{self.requests}/{self.total_seconds()}s"


class RatelimitIO:
    """Rate limiter for managing incoming and outgoing request limits."""

    def __init__(
        self,
        backend: Union[Redis, AsyncRedis],
        is_incoming: Optional[bool] = True,
        default_limit: Optional[LimitSpec] = None,
        default_key: Optional[str] = None,
    ):
        """
        Initializes the RatelimitIO instance.

        Args:
            backend (Redis | AsyncRedis): Redis backend instance.
            is_incoming (Optional[bool]): Mode of usage:
                - `True` for incoming requests
                    (raise an error if the limit is exceeded).
                - `False` for outgoing requests
                    (wait until a slot is available).
            default_limit (Optional[LimitSpec]): Default rate
                limit for the base URL.
            default_key (Optional[str]): Default unique key for rate limiting.

        Raises:
            RuntimeError: If the backend is not a supported Redis instance.
        """
        if not isinstance(backend, (Redis, AsyncRedis)):
            raise RuntimeError("Unsupported Redis backend.")

        self.backend = backend
        self.is_incoming = is_incoming
        self.default_limit = default_limit
        self.default_key = default_key

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
        self,
        func: Optional[Callable] = None,
        *,
        limit_spec: Optional[LimitSpec] = None,
        unique_key: Optional[str] = None,
    ) -> Callable:
        """
        Decorator for applying rate limits to functions.

        Args:
            func (Callable): Function to decorate.
            limit_spec (Optional[LimitSpec]): Rate limit specification.
                Defaults to `self.default_limit`.
            unique_key (Optional[str]): Optional unique key for rate limiting.
                If not provided, tries `self.default_key` or `kwargs["ip"]`.

        Returns:
            Callable: Decorated function.

        Raises:
            ValueError: If no rate limit specification is provided.
        """
        limit_spec = limit_spec or self.default_limit
        if not limit_spec:
            raise ValueError(
                "Rate limit specification is missing. Provide a limit_spec "
                "or ensure default_limit is set during initialization."
            )

        inferred_incoming = func is not None and callable(func)

        def decorator(
            func: Callable,
        ) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                key = self._prepare_key(
                    provided_key=None,
                    unique_key=unique_key,
                    func_name=func.__name__,
                    async_call=True,
                    **kwargs,
                )

                try:
                    await self.a_wait(key, limit_spec)
                except RatelimitIOError:
                    if inferred_incoming or self.is_incoming:
                        raise
                    raise RuntimeError(
                        f"Rate limit exceeded in {func.__name__}"
                    ) from None
                return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                key = self._prepare_key(
                    provided_key=None,
                    unique_key=unique_key,
                    func_name=func.__name__,
                    async_call=False,
                    **kwargs,
                )

                try:
                    self.wait(key, limit_spec)
                except RatelimitIOError:
                    if inferred_incoming or self.is_incoming:
                        raise
                    raise RuntimeError(
                        f"Rate limit exceeded in {func.__name__}"
                    ) from None
                return func(*args, **kwargs)

            return (
                async_wrapper
                if asyncio.iscoroutinefunction(func)
                else sync_wrapper
            )

        return decorator(func) if func and callable(func) else decorator

    async def __aenter__(self) -> "RatelimitIO":
        """
        Ensures the Lua script is loaded into Redis when entering the context.

        Returns:
            RatelimitIO: The instance of the rate limiter, ready for use.
        """
        await self._ensure_script_loaded_async()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Union[None, bool]:
        """
        Handles cleanup when exiting the context.

        Args:
            exc_type (Type): The type of exception raised (if any).
            exc_val (BaseException): The exception instance (if any).
            exc_tb (TracebackType): The traceback object (if any).

        Returns:
            Union[None, bool]: If returning `True`,
                suppresses the exception; otherwise, propagates it.
        """
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
                Defaults to `default_limit`.
            max_wait_time (float): Maximum wait time in seconds
                before raising an error.
            backoff_start (float): Initial backoff delay in seconds.
            backoff_max (float): Maximum backoff delay in seconds.

        Raises:
            RatelimitIOError: If the rate limit is exceeded and
                max wait time is reached.
        """
        if not limit_spec and not self.default_limit:
            raise ValueError(
                "limit_spec or self.default_limit must be provided."
            )

        limit_spec = limit_spec or self.default_limit

        self._ensure_script_loaded_sync()

        key = self._prepare_key(key)

        if self.is_incoming:
            if not self._enforce_limit_sync(key, limit_spec):  # type: ignore
                raise RatelimitExceededError()
            return

        start_time = time.time()
        backoff = backoff_start

        while not self._enforce_limit_sync(key, limit_spec):  # type: ignore
            if time.time() - start_time > max_wait_time:
                raise RatelimitExceededError(
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
                Defaults to `default_limit`.
            max_wait_time (float): Maximum wait time in seconds
                before raising an error.
            backoff_start (float): Initial backoff delay in seconds.
            backoff_max (float): Maximum backoff delay in seconds.

        Raises:
            RatelimitIOError: If the rate limit is exceeded and
                max wait time is reached.
        """
        if not limit_spec and not self.default_limit:
            raise ValueError(
                "limit_spec or self.default_limit must be provided."
            )

        limit_spec = limit_spec or self.default_limit

        await self._ensure_script_loaded_async()

        key = self._prepare_key(key)

        if self.is_incoming:
            if not await self._enforce_limit_async(
                key,
                limit_spec,  # type: ignore
            ):
                raise RatelimitExceededError()
            return

        start_time = time.time()
        backoff = backoff_start

        while not await self._enforce_limit_async(
            key,
            limit_spec,  # type: ignore
        ):
            if time.time() - start_time > max_wait_time:
                raise RatelimitExceededError(
                    f"Rate limit exceeded for {key}, wait time exceeded."
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)

    def _prepare_key(
        self,
        provided_key: Optional[str] = None,
        unique_key: Optional[str] = None,
        func_name: Optional[str] = None,
        async_call: bool = False,
        **kwargs,
    ) -> str:
        """
        Prepares the key based on priority and context, unifying logic for both
            decorator and manual call usage.

        Args:
            provided_key (Optional[str]): Directly provided key,
                highest priority.
            unique_key (Optional[str]): Unique key, e.g.,
                from a decorator call.
            func_name (Optional[str]): Name of the decorated function.
            async_call (bool): Whether the call is asynchronous.
            kwargs (Optional[dict]): Additional context, such as `ip`.

        Returns:
            str: Fully prepared Redis key.

        Raises:
            ValueError: If neither key nor base settings are provided.
        """
        key = (
            provided_key
            or unique_key
            or self.default_key
            or kwargs.get("ip", "unknown_key")
        )

        if func_name:
            key = (
                f"ratelimit"
                f":{'async' if async_call else 'sync'}:{key}:{func_name}"
            )

        return key

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
            return bool(
                self.backend.evalsha(
                    self._lua_script_hash,
                    1,
                    self._generate_key(key),
                    str(limit_spec.requests),
                    str(limit_spec.total_seconds()),
                )
            )
        except NoScriptError:
            self._ensure_script_loaded_sync()
            try:
                return bool(
                    self.backend.evalsha(
                        self._lua_script_hash,
                        1,
                        self._generate_key(key),
                        str(limit_spec.requests),
                        str(limit_spec.total_seconds()),
                    )
                )
            except NoScriptError as exc:
                raise ScriptLoadError() from exc

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
            return bool(
                await self.backend.evalsha(  # type: ignore
                    self._lua_script_hash,
                    1,
                    self._generate_key(key),
                    str(limit_spec.requests),
                    str(limit_spec.total_seconds()),
                )
            )
        except NoScriptError:
            await self._ensure_script_loaded_async()
            try:
                return bool(
                    await self.backend.evalsha(  # type: ignore
                        self._lua_script_hash,
                        1,
                        self._generate_key(key),
                        str(limit_spec.requests),
                        str(limit_spec.total_seconds()),
                    )
                )
            except NoScriptError as exc:
                raise ScriptLoadError() from exc

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
        try:
            if not self.backend.script_exists(  # type: ignore
                self._lua_script_hash
            )[0]:
                self.backend.script_load(self._lua_script)
            self._script_loaded = True
        except Exception as exc:
            logger.error(f"Failed to load Lua script into Redis: {exc}")
            raise ScriptLoadError() from exc

    async def _ensure_script_loaded_async(self) -> None:
        """Ensures the Lua script is loaded into Redis (asynchronously)."""
        try:
            if not (await self.backend.script_exists(self._lua_script_hash))[
                0
            ]:
                await self.backend.script_load(self._lua_script)
            self._script_loaded = True
        except Exception as exc:
            logger.error(f"Failed to load Lua script into Redis: {exc}")
            raise ScriptLoadError() from exc
