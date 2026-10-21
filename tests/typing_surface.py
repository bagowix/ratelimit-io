"""Static assertions for the public typing surface.

Never executed (no ``test_`` prefix): mypy, pyright and pyrefly all include
this file, so a regression in user-facing type inference fails CI even though
the runtime suite cannot observe it. A ``type: ignore`` line asserts that the
call is rejected: pyright and mypy both report an ignore that suppresses
nothing.
"""

# The assertion functions are intentionally never called.
# pyright: reportUnusedFunction=false

from typing import assert_type

from ratelimit_io import Key, Limit, RateLimiter


def _bare_decorator__keeps_the_signature(limiter: RateLimiter) -> None:
    @limiter
    def handler(user: str, *, verbose: bool = False) -> int:
        return len(user) + verbose

    assert_type(handler('alice', verbose=True), int)

    handler(1)  # type: ignore[arg-type]


async def _bare_decorator__keeps_the_async_signature(limiter: RateLimiter) -> None:
    @limiter
    async def handler(user: str) -> int:
        return len(user)

    assert_type(await handler('alice'), int)


def _decorator_with_options__keeps_the_signature(limiter: RateLimiter) -> None:
    @limiter(key='reports', max_wait=1.5)
    def handler(user: str) -> int:
        return len(user)

    assert_type(handler('alice'), int)


async def _decorator_with_options__keeps_the_async_signature(limiter: RateLimiter) -> None:
    def user_key(user: str) -> str:
        return user

    @limiter(key=user_key, limit=Limit(1, seconds=1), max_wait=5)
    async def handler(user: str) -> int:
        return len(user)

    assert_type(await handler('alice'), int)


def _key_template__keeps_the_signature(limiter: RateLimiter) -> None:
    @limiter(key=Key('user:{user}'))
    def handler(user: str) -> int:
        return len(user)

    assert_type(handler('alice'), int)


def _decorated_method__binds_self(limiter: RateLimiter) -> None:
    class Users:
        @limiter
        def get(self, user_id: int) -> str:
            return str(user_id)

    assert_type(Users().get(1), str)


def _wrap_call__keeps_the_signature(limiter: RateLimiter) -> None:
    def handler(user: str) -> int:
        return len(user)

    wrapped = limiter(handler, key='reports')

    assert_type(wrapped('alice'), int)


def _wrong_arguments__are_rejected(limiter: RateLimiter) -> None:
    limiter('reports')  # type: ignore[call-overload]

    Limit(1, 1)  # type: ignore[call-arg]

    Key(42)  # type: ignore[arg-type]

    limiter.acquire_sync(Key('user:{user}'))  # type: ignore[arg-type]


async def _acquire__returns_none(limiter: RateLimiter) -> None:
    assert_type(await limiter.acquire('key', limit=Limit(1, seconds=1)), None)
    assert_type(limiter.acquire_sync('key', max_wait=1.5), None)
