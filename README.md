# ratelimit-io

[![PyPI](https://img.shields.io/pypi/v/ratelimit-io.svg)](https://pypi.org/project/ratelimit-io/)
[![Downloads](https://img.shields.io/pypi/dm/ratelimit-io.svg)](https://pypi.org/project/ratelimit-io/)
[![Python versions](https://img.shields.io/pypi/pyversions/ratelimit-io.svg)](https://pypi.org/project/ratelimit-io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/bagowix/ratelimit-io/blob/main/LICENSE)
[![CI](https://github.com/bagowix/ratelimit-io/actions/workflows/ci.yml/badge.svg)](https://github.com/bagowix/ratelimit-io/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/bagowix/ratelimit-io/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-2f6f55.svg)](https://bagowix.github.io/ratelimit-io/)
[![llms.txt](https://img.shields.io/badge/-llms.txt-brightgreen)](https://bagowix.github.io/ratelimit-io/llms.txt)
[![Context7](https://img.shields.io/badge/docs-Context7-1f6feb.svg)](https://context7.com/bagowix/ratelimit-io)

Distributed rate limiting for Python on Redis. Every process that shares a
Redis server shares the limit: fixed window, sliding window or GCRA, each one
atomic Lua script, for async and sync code alike.

```python
from redis.asyncio import Redis

from ratelimit_io import Key, Limit, RateLimiter

limiter = RateLimiter(Redis(), limit=Limit(100, minutes=1))


@limiter(key=Key('user:{user_id}'))
async def search(user_id: int, query: str) -> list[str]: ...
```

The 101st call in a minute for one user raises `RateLimitExceededError`, and
its `retry_after`, rounded up, fills an HTTP `Retry-After` header.

**Documentation: <https://bagowix.github.io/ratelimit-io/>**

## Features

- **Three algorithms**: fixed window (the default), an exact sliding window,
  and GCRA, a token bucket in constant memory.
- **Incoming and outgoing requests.** `max_wait=0` refuses an over-limit
  request at once. With a wait budget the request reserves the next free slot
  in the same round trip and sleeps until it: no polling, first come first
  served across processes, and an early failure when the slot lies beyond the
  budget.
- **Async and sync in one class**: `await limiter.acquire()` with
  `redis.asyncio.Redis`, `limiter.acquire_sync()` with `redis.Redis`, and a
  decorator for both that keeps the function's signature.
- **Strict typing**: mypy, pyright and pyrefly in strict mode.
- **Hashed keys**: a bucket name holds the SHA-256 of its key, so raw keys
  stay out of Redis and every name has the same length.
- **Tested on real servers**: Python 3.11 to 3.15 against Redis 7, plus Redis
  5, Redis 6.2 and Valkey 8, including races between threads and tasks for one
  bucket.

## Install

```bash
pip install ratelimit-io
```

Requires Python 3.11+, redis-py 5.0.1+ and a Redis 5.0+ or Valkey server.

## Usage

```python
from redis import Redis

from ratelimit_io import Algorithm, Limit, RateLimiter, RateLimitExceededError

# Incoming requests: refuse at once.
api = RateLimiter(Redis(), limit=Limit(10, seconds=1))

try:
    api.acquire_sync('203.0.113.7')
except RateLimitExceededError as error:
    print(f'429, retry after {error.retry_after:.1f}s')

# Outgoing requests: wait up to 30 s for a slot, never exceed 5000 an hour.
github = RateLimiter(
    Redis(),
    limit=Limit(5000, hours=1),
    key='github',
    algorithm=Algorithm.SLIDING_WINDOW,
    max_wait=30,
)
github.acquire_sync()
```

Guides: [algorithms](https://bagowix.github.io/ratelimit-io/guides/algorithms/),
[keys and buckets](https://bagowix.github.io/ratelimit-io/guides/keys/),
[waiting](https://bagowix.github.io/ratelimit-io/guides/waiting/),
[FastAPI, Litestar, Django and Flask](https://bagowix.github.io/ratelimit-io/frameworks/).
Upgrading from 0.x? Read
[the migration guide](https://bagowix.github.io/ratelimit-io/migration/).

## Contributing

See [CONTRIBUTING.md](https://github.com/bagowix/ratelimit-io/blob/main/CONTRIBUTING.md).

## License

[MIT](https://github.com/bagowix/ratelimit-io/blob/main/LICENSE)
