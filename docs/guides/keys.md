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

1. the decorator's `key`: a string, or a function of the call's arguments;
2. the limiter's `key`;
3. the function's `module.qualname`, which gives every decorated function a
   bucket of its own.

```python
limiter = RateLimiter(client, limit=Limit(10, seconds=1))


@limiter  # bucket: 'shop.views.checkout'
async def checkout(order_id: int) -> None: ...


@limiter(key=lambda user_id, **_: f'user:{user_id}')  # one bucket per user
async def search(user_id: int, query: str) -> list[str]: ...
```

A key function receives the call's arguments by name, defaults included,
however the caller passed them: `search(42, 'shoes')` and
`search(user_id=42, query='shoes')` both reach it as `user_id=42,
query='shoes'`. Name the parameters you need and swallow the rest with `**_`.
On a method, `self` arrives too; `*args` and `**kwargs` parameters arrive under
their own names, as a tuple and a dict.

The arguments are bound to the signature of the function under `@limiter`,
seen through any `functools.wraps` wrapper. Put `@limiter` directly above the
`def`, below decorators that add or remove parameters, such as `mock.patch`.

It must return a non-empty string. An empty string is a bug in the function, so
it raises `ValueError`, and anything other than a string raises `TypeError`;
the limiter never falls back to a shared bucket.

Under strict pyright or pyrefly, prefer a typed function to a lambda: the
parameters of a lambda passed as `key` have no inferred types.

Functions made inside another function share a `module.qualname`, such as
`make_handler.<locals>.handler`, so every function one factory makes shares a
bucket. Give them a key when they should count apart.

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
