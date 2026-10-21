# Keys and buckets

A bucket is what a limit is counted in. Its identity has four parts:

- the **key**, such as `user:42` or the client's IP address;
- the **limit**, so `Limit(10, seconds=1)` and `Limit(1000, hours=1)` on one
  key count separately;
- the **algorithm**;
- the limiter's **`key_prefix`**, `ratelimit_io` by default.

Two calls share a bucket only when all four match.

## Keys for `acquire()`

The key is the first argument. Without one, the limiter's own `key` is used,
which suits a limiter that guards a single resource:

```python
github = RateLimiter(client, limit=Limit(5000, hours=1), key='github')

await github.acquire()  # the 'github' bucket
await github.acquire('search')  # the 'search' bucket
```

With neither, `acquire()` raises `ValueError`. Every request needs a bucket,
and the limiter never invents one.

## Keys for the decorator

The decorator finds the key of each call in this order:

1. the decorator's `key`: a string, a `Key` template, or a key function;
2. the limiter's `key`;
3. the function's `module.qualname`, which gives every decorated function a
   bucket of its own.

```python
from ratelimit_io import Key

limiter = RateLimiter(client, limit=Limit(10, seconds=1))


@limiter  # bucket: 'shop.views.checkout'
async def checkout(order_id: int) -> None: ...


@limiter(key=Key('user:{user_id}'))  # one bucket per user
async def search(user_id: int, query: str) -> list[str]: ...
```

Functions made inside another function share a `module.qualname`, such as
`make_handler.<locals>.handler`, so every function one factory makes shares a
bucket. Give them a key when they should count apart.

A `Key` template and a key function both see the call's arguments bound to the
signature of the function under `@limiter`, seen through any `functools.wraps`
wrapper. Put `@limiter` directly above the `def`, below decorators that add or
remove parameters, such as `mock.patch`.

### `Key` templates

`Key` fills a `str.format` template from the arguments of each call. A field
starts with the name of a parameter and may go on to attributes and items:
`Key('search:{request.client.host}')`, `Key('{headers[x-api-key]}')`.

The arguments are bound by name, defaults included, however the caller passed
them: `search(42, 'shoes')` and `search(user_id=42, query='shoes')` both fill
`user:42`. On a method, `self` is a parameter too, as in
`Key('account:{self.account_id}')`. `*args` and `**kwargs` parameters are
filled under their own names, as a tuple and a dict:
`Key('user:{kwargs[user_id]}')`.

The decorator checks the template when it is applied. A field that names no
parameter of the function raises `TypeError` at import time. A positional field
such as `{}` or `{0}`, an unknown conversion, and a field inside a format spec
such as `{user_id:{width}}` raise `ValueError` when the `Key` is created.
Doubled braces stay literal: `Key('{{tag}}:{user_id}')` fills `{tag}:42`.

A field that is `None` or an empty string raises `ValueError` on the call:
`user:None` would put every call without a user in one bucket. The limiter
never falls back to a shared bucket.

A plain string is never formatted. The decorator refuses a string `key` that
reads as a template, such as `key='user:{user_id}'`: as a literal it would be
one bucket for every call. The `ValueError` offers `Key('user:{user_id}')` to
fill it from the arguments, and `Key('user:{{user_id}}')` to keep the braces
and the bucket the literal key had. The limiter's own `key` and the key of
`acquire()` are used as they are.

### Key functions

When the key needs logic that a template cannot express, pass a function. It
receives the parameters it names, bound the same way, and returns the key:

```python
def account_key(user: User) -> str:
    if user.organization_id is not None:
        return f'org:{user.organization_id}'

    return f'user:{user.id}'


@limiter(key=account_key)  # members of an organization share its bucket
async def search(user: User, query: str) -> list[str]: ...
```

A key function that takes `**kwargs` receives every argument. A parameter the
decorated function lacks must have a default, or the decorator raises
`TypeError` at import time.

It must return a non-empty string. An empty string is a bug in the function, so
it raises `ValueError`, and anything other than a string raises `TypeError`.

## Several functions, one bucket

Give them the same key. A limiter-wide `key` does that for every function it
decorates, which is what an outgoing client wants:

```python
payments = RateLimiter(client, limit=Limit(100, seconds=1), key='payments-api', max_wait=5)


@payments
async def charge(card: str, amount: int) -> None: ...


@payments
async def refund(charge_id: str) -> None: ...
```

## Layered limits

Short bursts and long-term volume are separate limits, so take a slot from
each. The two limits count separately even on the same key:

```python
await limiter.acquire(user_key, limit=Limit(10, seconds=1))
await limiter.acquire(user_key, limit=Limit(1000, hours=1))
```

The calls are independent. A request that passes the first limit and fails
the second has still used a slot of the first.

## Hashed keys

Keys are hashed with SHA-256 before they reach Redis. A bucket looks like
`ratelimit_io:fixed_window:10/1000ms:9f86d0…`: the raw key appears neither in
the keyspace nor in `MONITOR` nor in a dump, and a long key makes a name as
short as any other.

A hash hides a key only from someone who cannot guess it. IPv4 addresses and
sequential user ids are few enough to hash every one of them, so whoever can
read the keyspace can recover such keys. Restrict access to Redis as you would
restrict access to the keys themselves.

## `key_prefix`

Every bucket lives under the limiter's `key_prefix`. Two applications that
share a Redis server and limit the same key under the same limit share a bucket
unless their prefixes differ:

```python
RateLimiter(client, limit=..., key_prefix='billing')
RateLimiter(client, limit=..., key_prefix='search')
```

Buckets expire on their own once nothing in them counts any more, so a prefix
never has to be cleaned up by hand.
