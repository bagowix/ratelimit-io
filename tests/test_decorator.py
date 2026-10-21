"""``@limiter`` and ``@limiter(...)``: keys, limits, clients and wrapping."""

import inspect
import time
from collections.abc import AsyncIterator, Callable, Iterator
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis as AsyncRedis

from conftest import LONG, MakeLimiter
from ratelimit_io import Key, Limit, RateLimiter, RateLimitExceededError

ONE = Limit(1, minutes=1)


def recording(received: list[dict[str, object]]) -> Callable[..., str]:
    """Return a key function that records the arguments it receives."""

    def key_func(**arguments: object) -> str:
        received.append(arguments)
        return 'recorded'

    return key_func


def numbers() -> Iterator[int]:
    yield 1


async def async_numbers() -> AsyncIterator[int]:
    yield 1


def test__decorator__bare__uses_the_limiter_limit(limiter: RateLimiter) -> None:
    calls: list[int] = []

    @limiter
    def handler(value: int) -> int:
        calls.append(value)
        return value * 2

    results = [handler(n) for n in range(LONG.requests)]

    with pytest.raises(RateLimitExceededError):
        handler(99)

    assert results == [0, 2, 4]
    assert calls == [0, 1, 2]


@pytest.mark.asyncio
async def test__decorator__bare_async__uses_the_limiter_limit(async_limiter: RateLimiter) -> None:
    calls: list[int] = []

    @async_limiter
    async def handler(value: int) -> int:
        calls.append(value)
        return value * 2

    results = [await handler(n) for n in range(LONG.requests)]

    with pytest.raises(RateLimitExceededError):
        await handler(99)

    assert results == [0, 2, 4]
    assert calls == [0, 1, 2]


def test__decorator__limit_option__beats_the_limiter_limit(limiter: RateLimiter) -> None:
    @limiter(limit=ONE)
    def handler() -> None: ...

    handler()

    with pytest.raises(RateLimitExceededError):
        handler()


@pytest.mark.asyncio
async def test__decorator__limit_option_on_async__beats_the_limiter_limit(
    async_limiter: RateLimiter,
) -> None:
    @async_limiter(limit=ONE)
    async def handler() -> None: ...

    await handler()

    with pytest.raises(RateLimitExceededError):
        await handler()


def test__decorator__no_key__gives_each_function_its_own_bucket(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter
    def first() -> None: ...

    @limiter
    def second() -> None: ...

    first()

    second()


def test__decorator__same_name_in_two_classes__counts_separately(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    class Users:
        @limiter
        def get(self) -> None: ...

    class Orders:
        @limiter
        def get(self) -> None: ...

    Users().get()

    Orders().get()


def test__decorator__same_name_in_two_modules__counts_separately(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    def handler() -> None: ...

    def twin() -> None: ...

    twin.__qualname__ = handler.__qualname__
    twin.__module__ = 'elsewhere'

    limiter(handler)()

    limiter(twin)()


def test__decorator__limiter_key__is_shared_by_functions(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(limit=ONE, key=key)

    @limiter
    def first() -> None: ...

    @limiter
    def second() -> None: ...

    first()

    with pytest.raises(RateLimitExceededError):
        second()


def test__decorator__key_option__beats_the_limiter_key(make_limiter: MakeLimiter, key: str) -> None:
    limiter = make_limiter(limit=ONE, key='shared')

    @limiter(key=key)
    def handler() -> None: ...

    handler()

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key)


def test__decorator__key_function__beats_the_limiter_key(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(limit=ONE, key='shared')

    @limiter(key=lambda: key)
    def handler() -> None: ...

    handler()

    limiter.acquire_sync()

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key)


def test__decorator__key_function__keys_each_call_by_its_arguments(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=lambda user, **_: user)
    def handler(user: str, *, verbose: bool = False) -> str:
        return f'{user}:{verbose}'

    assert handler('alice') == 'alice:False'
    assert handler('bob', verbose=True) == 'bob:True'

    with pytest.raises(RateLimitExceededError):
        handler('alice')


@pytest.mark.asyncio
async def test__decorator__key_function_on_async__keys_each_call_by_its_arguments(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE)

    @limiter(key=lambda user, **_: user)
    async def handler(user: str) -> str:
        return user

    assert await handler('alice') == 'alice'
    assert await handler('bob') == 'bob'

    with pytest.raises(RateLimitExceededError):
        await handler('alice')


def test__decorator__key_function__receives_arguments_by_name_with_defaults(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=LONG)
    received: list[dict[str, object]] = []

    @limiter(key=recording(received))
    def search(user_id: int, query: str = '') -> None: ...

    search(42, 'shoes')
    search(user_id=42)

    assert received == [{'user_id': 42, 'query': 'shoes'}, {'user_id': 42, 'query': ''}]


def test__decorator__key_function_on_a_method__receives_self(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=LONG)
    received: list[dict[str, object]] = []

    class Users:
        @limiter(key=recording(received))
        def get(self, user_id: int) -> None: ...

    users = Users()

    users.get(7)

    assert received == [{'self': users, 'user_id': 7}]


def test__decorator__key_function__receives_variadic_parameters_under_their_names(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=LONG)
    received: list[dict[str, object]] = []

    @limiter(key=recording(received))
    def handler(*items: int, **options: str) -> None: ...

    handler(1, 2, mode='fast')

    assert received == [{'items': (1, 2), 'options': {'mode': 'fast'}}]


def test__decorator__key_function_and_a_wrong_call__raises_before_taking_a_slot(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=lambda **_: key)
    def handler(user: str) -> None: ...

    with pytest.raises(TypeError, match="missing a required argument: 'user'"):
        handler()  # type: ignore[call-arg]

    limiter.acquire_sync(key)


def test__decorator__key_function_returns_empty__raises(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=lambda: '')
    def handler() -> None: ...

    with pytest.raises(ValueError, match=r'the key of .*handler must not be empty'):
        handler()


def test__decorator__key_function_returns_a_non_string__raises_type_error(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=lambda: 42)  # type: ignore[arg-type]
    def handler() -> None: ...

    with pytest.raises(TypeError, match=r'the key of .*handler must be a str, got int'):
        handler()


def test__decorator__key_function__receives_only_the_parameters_it_names(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=lambda user_id: f'user:{user_id}')
    def search(user_id: int, query: str) -> str:
        return f'{user_id}:{query}'

    assert search(42, 'shoes') == '42:shoes'

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('user:42')


@pytest.mark.asyncio
async def test__decorator__key_function_on_async__receives_only_the_parameters_it_names(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE)

    @limiter(key=lambda user_id: f'user:{user_id}')
    async def search(user_id: int, query: str) -> str:
        return f'{user_id}:{query}'

    assert await search(42, 'shoes') == '42:shoes'

    with pytest.raises(RateLimitExceededError):
        await limiter.acquire('user:42')


def test__decorator__key_function_parameter_with_a_default__keeps_the_default(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    def scoped(user_id: int, scope: str = 'search') -> str:
        return f'{scope}:{user_id}'

    @limiter(key=scoped)
    def search(user_id: int) -> None: ...

    search(42)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('search:42')


def test__decorator__str_format_as_key_function__receives_every_argument(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key='user:{user_id}'.format)
    def search(user_id: int, query: str) -> None: ...

    search(42, 'shoes')

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('user:42')


def test__decorator__key_function_without_a_readable_signature__receives_every_argument(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    class Unreadable:
        @property
        def __signature__(self) -> inspect.Signature:
            raise ValueError('no signature')

        def __call__(self, **arguments: object) -> str:
            return f'user:{arguments["user_id"]}'

    @limiter(key=Unreadable())
    def search(user_id: int, query: str) -> None: ...

    search(42, 'shoes')

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('user:42')


def test__decorator__key_function_names_no_parameter__raises_type_error(
    limiter: RateLimiter,
) -> None:
    def search(user_id: int) -> None: ...

    with pytest.raises(TypeError, match=r"search has no parameter 'usr_id' for its key"):
        limiter(search, key=lambda usr_id: f'user:{usr_id}')


def test__decorator__key_function_with_kwargs_names_no_parameter__raises_type_error(
    limiter: RateLimiter,
) -> None:
    def search(user_id: int) -> None: ...

    with pytest.raises(TypeError, match=r"search has no parameter 'usr_id' for its key"):
        limiter(search, key=lambda usr_id, **_: f'user:{usr_id}')


def test__decorator__key_template__keys_each_call_by_its_arguments(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=Key('user:{user_id}'))
    def search(user_id: int, query: str) -> str:
        return f'{user_id}:{query}'

    assert search(42, 'shoes') == '42:shoes'
    assert search(7, 'hats') == '7:hats'

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('user:42')


@pytest.mark.asyncio
async def test__decorator__key_template_on_async__keys_each_call_by_its_arguments(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE)

    @limiter(key=Key('user:{user_id}'))
    async def search(user_id: int, query: str) -> str:
        return f'{user_id}:{query}'

    assert await search(42, 'shoes') == '42:shoes'
    assert await search(7, 'hats') == '7:hats'

    with pytest.raises(RateLimitExceededError):
        await limiter.acquire('user:42')


def test__decorator__key_template__binds_arguments_by_name_with_defaults(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=Key('{user_id}:{page}'))
    def search(user_id: int, page: int = 1) -> None: ...

    search(42)

    with pytest.raises(RateLimitExceededError):
        search(user_id=42, page=1)


def test__decorator__key_template__reads_attributes(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)
    request = SimpleNamespace(client=SimpleNamespace(host='203.0.113.7'))

    @limiter(key=Key('ip:{request.client.host}'))
    def handler(request: SimpleNamespace) -> None: ...

    handler(request)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('ip:203.0.113.7')


def test__decorator__key_template__reads_items(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=Key('api-key:{headers[x-api-key]}'))
    def handler(headers: dict[str, str]) -> None: ...

    handler({'x-api-key': 'k1'})

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('api-key:k1')


def test__decorator__key_template_on_a_method__reads_self(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    class Tenant:
        name = 'acme'

        @limiter(key=Key('{self.name}:{user_id}'))
        def search(self, user_id: int) -> None: ...

    Tenant().search(42)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('acme:42')


def test__decorator__key_template_with_doubled_braces__keeps_them_literal(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=Key('{{tag}}:{user_id}'))
    def search(user_id: int) -> None: ...

    search(42)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('{tag}:42')


def test__decorator__key_template_names_no_parameter__raises_type_error(
    limiter: RateLimiter,
) -> None:
    def search(user_id: int) -> None: ...

    with pytest.raises(TypeError, match=r"search has no parameter 'usr_id' for its key"):
        limiter(search, key=Key('user:{usr_id.name}'))


def test__decorator__plain_key_with_a_field__raises_and_names_both_fixes(
    limiter: RateLimiter,
) -> None:
    def search(user_id: int) -> None: ...

    with pytest.raises(
        ValueError,
        match=r"Key\('user:\{user_id\}'\).*Key\('user:\{\{user_id\}\}'\)",
    ):
        limiter(search, key='user:{user_id}')


def test__decorator__plain_key_with_unbalanced_braces__stays_literal(
    make_limiter: MakeLimiter,
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key='user:}')
    def handler() -> None: ...

    handler()

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync('user:}')


def test__decorator__limiter_key_with_braces__is_used_as_it_is(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE, key='user:{user_id}')

    @limiter
    def search(user_id: int) -> None: ...

    search(42)

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync()


@pytest.mark.parametrize('user_id', [None, ''])
def test__decorator__key_template_field_is_none_or_empty__raises_before_taking_a_slot(
    make_limiter: MakeLimiter, user_id: str | None
) -> None:
    limiter = make_limiter(limit=ONE)

    @limiter(key=Key('user:{user_id}'))
    def search(user_id: str | None) -> None: ...

    with pytest.raises(ValueError, match=r'the key of .*search: \{user_id\} is'):
        search(user_id)

    limiter.acquire_sync(f'user:{user_id}')


def test__decorator__empty_key__raises(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    with pytest.raises(ValueError, match='key must not be empty'):
        limiter(key='')


def test__decorator__key_not_a_string__raises_type_error(limiter: RateLimiter) -> None:
    with pytest.raises(TypeError, match='key must be a str, got int'):
        limiter(key=42)  # type: ignore[call-overload]


def test__decorator__invalid_max_wait__raises(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    with pytest.raises(ValueError, match='max_wait must be >= 0'):
        limiter(max_wait=-1)


def test__decorator__no_limit_anywhere__raises(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter()

    with pytest.raises(ValueError, match='no limit'):
        limiter(key='key')


@pytest.mark.asyncio
async def test__decorator__plain_function_on_async_client__raises_type_error(
    async_limiter: RateLimiter,
) -> None:
    def handler() -> None: ...

    with pytest.raises(TypeError, match='is not a coroutine function'):
        async_limiter(handler)


def test__decorator__coroutine_function_on_sync_client__raises_type_error(
    limiter: RateLimiter,
) -> None:
    async def handler() -> None: ...

    with pytest.raises(TypeError, match='is a coroutine function'):
        limiter(handler)


@pytest.mark.asyncio
async def test__decorator__instance_with_async_call__is_awaited(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis, key: str
) -> None:
    limiter = make_limiter(async_redis_client, limit=ONE)

    class Handler:
        async def __call__(self, value: int) -> int:
            return value * 2

    wrapped = limiter(Handler(), key=key)

    assert await wrapped(21) == 42

    with pytest.raises(RateLimitExceededError):
        await wrapped(21)


def test__decorator__callable_without_a_name_or_key__raises_type_error(
    limiter: RateLimiter,
) -> None:
    class Handler:
        def __call__(self) -> None: ...

    with pytest.raises(TypeError, match='pass key='):
        limiter(Handler())


@pytest.mark.parametrize('wrap', [staticmethod, classmethod])
def test__decorator__above_staticmethod_or_classmethod__raises_type_error(
    limiter: RateLimiter, wrap: type
) -> None:
    def handler() -> None: ...

    with pytest.raises(TypeError, match=f'put @limiter below @{wrap.__name__}'):
        limiter(wrap(handler))  # type: ignore[arg-type]


def test__decorator__below_classmethod__rate_limits_the_method(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=ONE)

    class Users:
        @classmethod
        @limiter
        def count(cls) -> int:
            return 0

    assert Users.count() == 0

    with pytest.raises(RateLimitExceededError):
        Users().count()


def test__decorator__not_callable__raises_type_error(limiter: RateLimiter) -> None:
    with pytest.raises(TypeError, match=r'got str; pass options by keyword'):
        limiter('reports')  # type: ignore[call-overload]


@pytest.mark.parametrize('func', [numbers, async_numbers])
def test__decorator__generator_function__raises_type_error(
    limiter: RateLimiter, func: Callable[[], object]
) -> None:
    with pytest.raises(TypeError, match='is a generator function'):
        limiter(func)


def test__decorator__function_and_options_in_one_call__wraps_the_function(
    make_limiter: MakeLimiter, key: str
) -> None:
    limiter = make_limiter(limit=ONE)

    def handler() -> str:
        return 'done'

    wrapped = limiter(handler, key=key)

    assert wrapped() == 'done'

    with pytest.raises(RateLimitExceededError):
        limiter.acquire_sync(key)


def test__decorator__wrapper__keeps_the_function_metadata(limiter: RateLimiter) -> None:
    def handler() -> None:
        """Handle a request."""

    wrapped = limiter(handler)

    assert wrapped.__name__ == 'handler'
    assert wrapped.__doc__ == 'Handle a request.'
    assert wrapped.__wrapped__ is handler  # type: ignore[attr-defined]


def test__decorator__function_raises__propagates(limiter: RateLimiter) -> None:
    @limiter
    def handler() -> None:
        raise LookupError

    with pytest.raises(LookupError):
        handler()


@pytest.mark.asyncio
async def test__decorator__async_wrapper__forwards_keyword_arguments(
    async_limiter: RateLimiter,
) -> None:
    @async_limiter
    async def handler(value: int, *, scale: int) -> int:
        return value * scale

    assert await handler(2, scale=3) == 6


def test__decorator__max_wait_option__waits_for_the_next_slot(make_limiter: MakeLimiter) -> None:
    limiter = make_limiter(limit=Limit(1, seconds=0.2))

    @limiter(max_wait=2)
    def handler() -> None: ...

    handler()
    started = time.monotonic()

    handler()

    assert time.monotonic() - started >= 0.1


@pytest.mark.asyncio
async def test__decorator__max_wait_option_on_async__waits_for_the_next_slot(
    make_limiter: MakeLimiter, async_redis_client: AsyncRedis
) -> None:
    limiter = make_limiter(async_redis_client, limit=Limit(1, seconds=0.2))

    @limiter(max_wait=2)
    async def handler() -> None: ...

    await handler()
    started = time.monotonic()

    await handler()

    assert time.monotonic() - started >= 0.1
