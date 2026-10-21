"""The ``RateLimiter``: acquire, acquire_sync and the decorator."""

import asyncio
import functools
import hashlib
import inspect
import numbers
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ParamSpec, TypeAlias, TypeVar, cast, overload

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import NoScriptError

from ratelimit_io._algorithm import Algorithm
from ratelimit_io._errors import RateLimitExceededError
from ratelimit_io._key import Key, check_plain_key, template_key
from ratelimit_io._limit import Limit
from ratelimit_io._scripts import SCRIPTS

__all__ = ('RateLimiter',)

P = ParamSpec('P')
R = TypeVar('R')

# KEYS[1] and ARGV[1..4] of every script; see ratelimit_io._scripts.
_ScriptArgs: TypeAlias = tuple[str, int, int, float, str]

# What the decorator accepts as the key of each call.
_DecoratorKey: TypeAlias = str | Key | Callable[..., str]

# @limiter above one of these would turn the descriptor into a plain function;
# they belong above @limiter.
_METHOD_DESCRIPTORS: tuple[type, ...] = (staticmethod, classmethod)


class RateLimiter:
    """A distributed rate limiter on Redis.

    One class for async and sync code, like ``run`` and ``run_sync`` in
    pydantic-ai: ``acquire()`` takes a slot through a ``redis.asyncio.Redis``
    client, ``acquire_sync()`` through a ``redis.Redis`` one, and the decorator
    picks the one that matches the function it wraps.

    A request that finds no free slot fails with ``RateLimitExceededError``,
    unless the next free slot is at most ``max_wait`` seconds away: then the
    request reserves it and sleeps until it comes. ``0``, the default, suits
    incoming requests a server sheds; a budget suits outgoing requests a client
    has to send sooner or later. Waiting requests are served in arrival order,
    across every process that shares the bucket.

    A bucket is one key under one algorithm and one ``Limit``, so two limits on
    the same key (say 10/s and 1000/h) count separately. Keys are hashed before
    they reach Redis, which keeps client data such as IP addresses out of the
    keyspace.

    Args:
        client: The Redis client that holds the buckets.
        limit: The limit used when a call names none.
        key: The bucket key used when a call names none.
        algorithm: How requests are counted; see ``Algorithm``.
        max_wait: Seconds a request may wait for a slot. ``0`` fails at once,
            ``math.inf`` waits as long as it takes.
        key_prefix: The namespace of every bucket in Redis. Give each
            application that shares a server its own, or equal keys under equal
            limits share one bucket across applications.

    Raises:
        TypeError: If ``client`` is not a ``redis.Redis`` or
            ``redis.asyncio.Redis`` client, or another option has the wrong
            type.
        ValueError: If ``key`` or ``key_prefix`` is empty, ``max_wait`` is
            negative, or ``algorithm`` names no ``Algorithm``.
    """

    def __init__(  # noqa: PLR0913 - every limiter setting is a keyword-only knob
        self,
        client: Redis | AsyncRedis,
        *,
        limit: Limit | None = None,
        key: str | None = None,
        algorithm: Algorithm = Algorithm.FIXED_WINDOW,
        max_wait: float = 0,
        key_prefix: str = 'ratelimit_io',
    ) -> None:
        self._limit = None if limit is None else _check_limit(limit)
        self._key = None if key is None else _check_key(key, 'key')
        self._algorithm = Algorithm(algorithm)
        self._max_wait = _check_max_wait(max_wait)
        self._key_prefix = _check_key(key_prefix, 'key_prefix')

        self._script = SCRIPTS[self._algorithm]
        self._script_sha = hashlib.sha1(self._script.encode(), usedforsecurity=False).hexdigest()

        self._sync_client: Redis | None = None
        self._async_client: AsyncRedis | None = None

        if isinstance(client, AsyncRedis):
            self._async_client = client
        elif isinstance(client, Redis):  # pyright: ignore[reportUnnecessaryIsInstance] - checks untyped callers
            self._sync_client = client
        else:
            raise TypeError(
                'client must be a redis.Redis or redis.asyncio.Redis client, '
                f'got {type(client).__name__}'
            )

    def __repr__(self) -> str:
        return (
            f'{type(self).__name__}(limit={self._limit!r}, key={self._key!r}, '
            f'algorithm={self._algorithm.value!r}, max_wait={self._max_wait!r}, '
            f'key_prefix={self._key_prefix!r})'
        )

    async def acquire(
        self,
        key: str | None = None,
        *,
        limit: Limit | None = None,
        max_wait: float | None = None,
    ) -> None:
        """Take one slot from the bucket of ``key``, waiting up to ``max_wait`` for it.

        Args:
            key: The bucket key. Defaults to the limiter's ``key``.
            limit: The limit. Defaults to the limiter's ``limit``.
            max_wait: Overrides the limiter's ``max_wait`` for this call.

        Raises:
            RateLimitExceededError: If the next free slot is more than
                ``max_wait`` seconds away.
            TypeError: If the limiter has a sync client; use ``acquire_sync()``.
            ValueError: If no key or no limit is given and the limiter has none.
        """
        client = self._async_client
        if client is None:
            raise TypeError(
                'acquire() needs a redis.asyncio.Redis client; use acquire_sync() with a sync one'
            )

        resolved = self._resolve_limit(limit)
        wait_ms = await self._run(client, self._script_args(key, resolved, max_wait))

        if wait_ms < 0:
            raise RateLimitExceededError(resolved, -wait_ms / 1000)

        if wait_ms:
            await asyncio.sleep(wait_ms / 1000)

    def acquire_sync(
        self,
        key: str | None = None,
        *,
        limit: Limit | None = None,
        max_wait: float | None = None,
    ) -> None:
        """Blocking twin of ``acquire()``, for a ``redis.Redis`` client.

        Raises:
            RateLimitExceededError: If the next free slot is more than
                ``max_wait`` seconds away.
            TypeError: If the limiter has an async client; use ``acquire()``.
            ValueError: If no key or no limit is given and the limiter has none.
        """
        client = self._sync_client
        if client is None:
            raise TypeError(
                'acquire_sync() needs a redis.Redis client; use acquire() with an async one'
            )

        resolved = self._resolve_limit(limit)
        wait_ms = self._run_sync(client, self._script_args(key, resolved, max_wait))

        if wait_ms < 0:
            raise RateLimitExceededError(resolved, -wait_ms / 1000)

        if wait_ms:
            time.sleep(wait_ms / 1000)

    @overload
    def __call__(
        self,
        func: Callable[P, R],
        /,
        *,
        key: _DecoratorKey | None = None,
        limit: Limit | None = None,
        max_wait: float | None = None,
    ) -> Callable[P, R]: ...

    @overload
    def __call__(
        self,
        func: None = None,
        /,
        *,
        key: _DecoratorKey | None = None,
        limit: Limit | None = None,
        max_wait: float | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def __call__(
        self,
        func: Callable[P, R] | None = None,
        /,
        *,
        key: _DecoratorKey | None = None,
        limit: Limit | None = None,
        max_wait: float | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Rate limit every call of a function.

        Works as ``@limiter``, as ``@limiter(...)`` with options, and as a plain
        call ``limiter(func, ...)`` for a function defined elsewhere. Coroutine
        functions take their slot with ``acquire()``, plain functions with
        ``acquire_sync()``, so the client must match the function.

        The bucket key of a call is, in order of precedence: ``key``, the
        limiter's ``key``, or the function's ``module.qualname``, which gives
        the function a bucket of its own. ``key`` is a string, a ``Key``
        template filled from the call's arguments, or a function that receives
        the arguments it names and returns the key.

        Args:
            func: The function to rate limit; omitted when options come first.
            key: The bucket key, a ``Key`` template, or a key function.
            limit: The limit. Defaults to the limiter's ``limit``.
            max_wait: Overrides the limiter's ``max_wait`` for these calls.

        Returns:
            The wrapped function, or a decorator when called without one.

        Raises:
            TypeError: If the target is not a plain or coroutine function
                (staticmethod, classmethod and generator functions are
                refused), its nature does not match the client, ``key`` asks
                for a parameter the function does not have, or an option has
                the wrong type.
            ValueError: If ``key`` is empty or a string that reads as a ``Key``
                template, ``max_wait`` is negative, or no limit is given and the
                limiter has none.
        """
        if key is not None and not isinstance(key, Key) and not callable(key):
            _check_key(key, 'key')

        if max_wait is not None:
            _check_max_wait(max_wait)

        resolved = self._resolve_limit(limit)

        def decorate(target: Callable[P, R]) -> Callable[P, R]:
            return self._decorate(target, key=key, limit=resolved, max_wait=max_wait)

        return decorate if func is None else decorate(func)

    def _decorate(
        self,
        func: Callable[P, R],
        *,
        key: _DecoratorKey | None,
        limit: Limit,
        max_wait: float | None,
    ) -> Callable[P, R]:
        _check_target(func)
        key_of = self._key_of(func, key)

        if _is_coroutine_function(func):
            if self._async_client is None:
                raise TypeError(
                    f'{_name_of(func)} is a coroutine function; '
                    'rate limit it with a redis.asyncio.Redis client'
                )

            async_func = cast('Callable[P, Awaitable[Any]]', func)

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:  # noqa: ANN401 - forwards the wrapped coroutine's result
                await self.acquire(key_of(*args, **kwargs), limit=limit, max_wait=max_wait)
                return await async_func(*args, **kwargs)

            return cast('Callable[P, R]', async_wrapper)

        if self._sync_client is None:
            raise TypeError(
                f'{_name_of(func)} is not a coroutine function; '
                'rate limit it with a redis.Redis client'
            )

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            self.acquire_sync(key_of(*args, **kwargs), limit=limit, max_wait=max_wait)
            return func(*args, **kwargs)

        return sync_wrapper

    def _key_of(self, func: Callable[..., Any], key: _DecoratorKey | None) -> Callable[..., str]:
        """Return the function that names the bucket of each call of ``func``."""
        if isinstance(key, Key) or callable(key):
            return _computed_key(func, key)

        if key is not None:
            check_plain_key(key, _name_of(func))
            static = key
        elif self._key is not None:
            static = self._key
        else:
            static = _default_key(func)

        def constant(*_args: object, **_kwargs: object) -> str:
            return static

        return constant

    def _resolve_limit(self, limit: Limit | None) -> Limit:
        if limit is not None:
            return _check_limit(limit)

        if self._limit is None:
            raise ValueError('no limit: pass limit or set one on the limiter')

        return self._limit

    def _resolve_key(self, key: str | None) -> str:
        if key is not None:
            return _check_key(key, 'key')

        if self._key is None:
            raise ValueError('no key: pass key or set one on the limiter')

        return self._key

    def _bucket(self, key: str, limit: Limit) -> str:
        # surrogatepass: a key decoded with surrogateescape still hashes.
        digest = hashlib.sha256(key.encode('utf-8', 'surrogatepass')).hexdigest()

        return (
            f'{self._key_prefix}:{self._algorithm}:{limit.requests}/{limit.period_ms()}ms:{digest}'
        )

    def _script_args(self, key: str | None, limit: Limit, max_wait: float | None) -> _ScriptArgs:
        budget = self._max_wait if max_wait is None else _check_max_wait(max_wait)

        # An infinite budget travels as 'inf', which Lua reads back as infinity.
        # The sliding window logs each slot under its own member.
        return (
            self._bucket(self._resolve_key(key), limit),
            limit.requests,
            limit.period_ms(),
            budget * 1000,
            uuid.uuid4().hex,
        )

    # Redis forgets scripts on restart, on failover and on SCRIPT FLUSH. EVAL
    # then sends the source and caches it again in one command; SCRIPT LOAD
    # followed by EVALSHA would leave room for another flush in between.
    async def _run(self, client: AsyncRedis, args: _ScriptArgs) -> int:
        try:
            return int(await client.evalsha(self._script_sha, 1, *args))
        except NoScriptError:
            return int(await client.eval(self._script, 1, *args))

    def _run_sync(self, client: Redis, args: _ScriptArgs) -> int:
        try:
            return int(client.evalsha(self._script_sha, 1, *args))
        except NoScriptError:
            return int(client.eval(self._script, 1, *args))


def _check_key(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{what} must be a str, got {type(value).__name__}')

    if not value:
        raise ValueError(f'{what} must not be empty')

    return value


def _check_limit(value: object) -> Limit:
    if not isinstance(value, Limit):
        raise TypeError(f'limit must be a Limit, got {type(value).__name__}')

    return value


def _check_max_wait(value: object) -> float:
    # bool is an int, and max_wait=True reads like a switch, not one second.
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f'max_wait must be a number of seconds, got {type(value).__name__}')

    seconds = float(value)
    if not seconds >= 0:
        raise ValueError(f'max_wait must be >= 0, got {value!r}')

    return seconds


def _check_target(func: object) -> None:
    if isinstance(func, _METHOD_DESCRIPTORS):
        kind = type(func).__name__
        raise TypeError(f'cannot rate limit a {kind} object; put @limiter below @{kind}')

    if not callable(func):
        raise TypeError(
            f'expected a function to rate limit, got {type(func).__name__}; '
            'pass options by keyword: @limiter(key=...)'
        )

    if inspect.isgeneratorfunction(func) or inspect.isasyncgenfunction(func):
        raise TypeError(
            f'{_name_of(func)} is a generator function: a limit would count the '
            'generators it creates, not the items they yield. Call acquire() or '
            'acquire_sync() inside it instead'
        )


def _is_coroutine_function(func: object) -> bool:
    # An object with an async __call__ is no coroutine function to inspect.
    return inspect.iscoroutinefunction(func) or inspect.iscoroutinefunction(type(func).__call__)


def _name_of(func: object) -> str:
    qualname = getattr(func, '__qualname__', None)

    return qualname if isinstance(qualname, str) else repr(func)


def _default_key(func: object) -> str:
    qualname = getattr(func, '__qualname__', None)
    if not isinstance(qualname, str):
        raise TypeError(f'{func!r} has no __qualname__ to name its bucket; pass key=')

    return f'{getattr(func, "__module__", None)}.{qualname}'


def _computed_key(func: Callable[..., Any], key: Key | Callable[..., str]) -> Callable[..., str]:
    """Compute the key of each call from its arguments, bound by name, defaults included."""
    signature = inspect.signature(func)
    name = _name_of(func)
    compute = (
        template_key(key, signature, name)
        if isinstance(key, Key)
        else _function_key(key, signature, name)
    )

    def computed(*args: object, **kwargs: object) -> str:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        return _check_key(compute(bound.arguments), f'the key of {name}')

    return computed


def _function_key(
    key_func: Callable[..., str], signature: inspect.Signature, name: str
) -> Callable[[Mapping[str, object]], str]:
    """Call ``key_func`` with the arguments it names, or with all when it takes ``**kwargs``."""
    # Some callables, such as str.format before Python 3.13, have no readable
    # signature. They receive every argument, as a key function with **kwargs does.
    try:
        parameters = inspect.signature(key_func).parameters.values()
    except ValueError:
        return lambda arguments: key_func(**arguments)

    by_name = [
        parameter
        for parameter in parameters
        if parameter.kind in {parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY}
    ]

    for parameter in by_name:
        if parameter.name not in signature.parameters and parameter.default is parameter.empty:
            raise TypeError(f'{name} has no parameter {parameter.name!r} for its key function')

    if any(parameter.kind is parameter.VAR_KEYWORD for parameter in parameters):
        return lambda arguments: key_func(**arguments)

    names = tuple(parameter.name for parameter in by_name if parameter.name in signature.parameters)

    return lambda arguments: key_func(**{wanted: arguments[wanted] for wanted in names})
