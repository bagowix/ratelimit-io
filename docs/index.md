# ratelimit-io

Distributed rate limiting for Python on Redis. Every process that shares a
Redis server shares the limit, so ten replicas of a service enforce one limit
between them.

```python
from redis.asyncio import Redis

from ratelimit_io import Limit, RateLimiter

limiter = RateLimiter(Redis(), limit=Limit(100, minutes=1))


@limiter(key=lambda user_id, **_: f'user:{user_id}')
async def search(user_id: int, query: str) -> list[str]: ...
```

The 101st call in a minute for one user raises `RateLimitExceededError`, and
its `retry_after` says how many seconds to wait. Round it up for an HTTP
`Retry-After` header, which takes whole seconds.

## Why ratelimit-io

- **Three algorithms**, each one atomic Lua script on the server:
  [fixed window, sliding window and GCRA](guides/algorithms.md). Fixed window
  is the default.
- **Incoming and outgoing requests.** A server sheds load with `max_wait=0`
  and refuses at once. A client that has to make the call sooner or later
  passes a wait budget: the request reserves the next free slot in one round
  trip and sleeps until it, and waiters are served in arrival order across
  processes.
- **Async and sync in one class**, like `run` and `run_sync` in pydantic-ai:
  `await limiter.acquire()` with `redis.asyncio.Redis`, `limiter.acquire_sync()`
  with `redis.Redis`, and a decorator that serves both.
- **Typed.** The decorator keeps the wrapped function's signature, and the
  package passes mypy, pyright and pyrefly in strict mode.
- **Hashed keys.** A bucket name holds the SHA-256 of its key, so raw keys
  stay out of Redis and every name has the same length. A hash of an IP
  address can still be guessed: see [Hashed keys](guides/keys.md#hashed-keys).
- **Tested against real servers.** CI runs every test on Python 3.11 to 3.15
  against Redis 7, and against Redis 5, Redis 6.2 and Valkey 8, including races
  between threads and tasks for one bucket.

## Install

```bash
pip install ratelimit-io
```

The only dependency is [redis-py](https://github.com/redis/redis-py) 5.0.1 or
newer. Any Redis 5.0+ or Valkey server works, Sentinel included.
Redis Cluster is not supported yet.

Next: [Getting started](getting-started.md).
