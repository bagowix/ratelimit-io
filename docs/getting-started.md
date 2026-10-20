# Getting started

## Install

```bash
pip install ratelimit-io
```

You need a Redis 5.0+ or Valkey server. Redis 5 predates the RESP3 protocol
that redis-py 8 speaks by default, so for it pass `protocol=2` to the client.
For local work:

```bash
docker run --rm -p 6379:6379 redis:7
```

## Your first limiter

A `RateLimiter` holds a Redis client and the defaults for its calls: the
`Limit`, an optional bucket `key`, the counting `algorithm` and how long a
refused request may wait (`max_wait`).

```python
from redis.asyncio import Redis

from ratelimit_io import Limit, RateLimiter, RateLimitExceededError

limiter = RateLimiter(Redis(), limit=Limit(5, seconds=1))


async def handle(user_id: int) -> None:
    try:
        await limiter.acquire(f'user:{user_id}')
    except RateLimitExceededError as error:
        print(f'slow down, retry in {error.retry_after:.1f}s')
        return

    ...  # the request is within the limit
```

`acquire()` takes one request from the bucket of the key. The sixth call in a
second for one user raises `RateLimitExceededError`. The error carries the
`limit` that refused the request and `retry_after`, the seconds until a request
on that key can pass again.

## Sync code

Pass a `redis.Redis` client and call `acquire_sync()`. Everything else is the
same.

```python
from redis import Redis

from ratelimit_io import Limit, RateLimiter

sync_limiter = RateLimiter(Redis(), limit=Limit(5, seconds=1))

sync_limiter.acquire_sync('user:42')
```

The client decides which method works: `acquire()` needs a
`redis.asyncio.Redis`, `acquire_sync()` needs a `redis.Redis`. The other one
raises `TypeError` and names the method to use.

## The decorator

The limiter is also a decorator. It takes a slot before each call and keeps the
function's signature for type checkers.

```python
@limiter
async def export_report() -> bytes: ...


@limiter(key=lambda user_id, **_: f'user:{user_id}', limit=Limit(10, minutes=1))
async def search(user_id: int, query: str) -> list[str]: ...
```

Without a key, a decorated function gets a bucket of its own, named after its
module and qualified name. A string `key` names the bucket directly, and a
function `key` computes it from each call's arguments. See
[Keys and buckets](guides/keys.md).

Coroutine functions need an async client and plain functions a sync one. The
decorator checks this when it is applied, so a mismatch fails at import time
rather than on the first request.

## Waiting instead of failing

A server should refuse an over-limit request at once: that is the default,
`max_wait=0`. A client calling someone else's API usually has to make the call
anyway, so it waits for a slot:

```python
github = RateLimiter(Redis(), limit=Limit(5000, hours=1), key='github', max_wait=30)


async def fetch_repo(name: str) -> None:
    await github.acquire()  # sleeps until a slot frees up, up to 30 s
    ...
```

When the bucket is full, the limiter reserves the next free slot in the same
round trip and sleeps until it, so it never polls Redis. When that slot lies
beyond the budget it reserves nothing and raises straight away instead of
sleeping in vain. See [Waiting for a slot](guides/waiting.md).

A sleeping request holds no connection, but a burst of requests needs one per
request in flight. When a burst can outgrow the client's connection pool, read
[Connections and retries](guides/waiting.md#connections-and-retries).

## Answering with HTTP 429

`retry_after` is a float; the `Retry-After` header takes whole seconds, so
round it up:

```python
import math

headers = {'Retry-After': str(math.ceil(error.retry_after))}
```

[Frameworks](frameworks.md) shows the full setup for FastAPI, Django and Flask.

## Next steps

- [Algorithms](guides/algorithms.md): fixed window, sliding window, GCRA, and
  which one to pick.
- [Keys and buckets](guides/keys.md): per-user limits, shared limits, layered
  limits, `key_prefix`.
- [Reference](reference.md): every public name.
