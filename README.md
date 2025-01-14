# RatelimitIO

A Python library for rate limiting, supporting both synchronous and asynchronous paradigms. Built on Redis, this library provides decorators, context managers, and easy integration with APIs to manage incoming and outgoing request limits effectively.

#### Project Information
[![Tests & Lint](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml/badge.svg)](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/bagowix/1ecff0cf19b2940c0053e79d41963602/raw/98e31937c460d2d16748cb11adc7ce80d77d9a94/ratelimit-io-coverage.json&style=flat)](https://gist.githubusercontent.com/bagowix/1ecff0cf19b2940c0053e79d41963602/raw/98e31937c460d2d16748cb11adc7ce80d77d9a94/ratelimit-io-coverage.json)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ratelimit-io)](https://pypi.org/project/ratelimit-io/)
[![License](https://img.shields.io/pypi/l/ratelimitio)](LICENSE)


---

## Features

- **Synchronous and Asynchronous Support**: Works seamlessly in both paradigms.
- **Redis Backend**: Leverages Redis for fast and scalable rate limiting.
- **Flexible API**:
  - Use as a **decorator** for methods or functions.
  - Use as a **context manager**.
  - Integrate directly into API clients or middlewares.
- **Customizable Rate Limits**: Specify limits per key, time period, and requests.
- **Robust Lua Script**: Efficient and atomic rate limiting logic.

---

## Installation

Install via pip:

```bash
pip install ratelimit-io
```

## Quick Start

### Using as a Synchronous Decorator

```python
from ratelimit_io import RatelimitIO, LimitSpec
from redis import Redis

redis_client = Redis(host="localhost", port=6379)
limiter = RatelimitIO(backend=redis_client)

@limiter(LimitSpec(requests=10, seconds=60), unique_key="user:123")
def fetch_data():
    return "Request succeeded!"

# Use the decorated function
fetch_data()
```

### Using as a Asynchronous Decorator

```python
from ratelimit_io import RatelimitIO, LimitSpec
from redis.asyncio import Redis as AsyncRedis

async_redis_client = AsyncRedis(host="localhost", port=6379)
async_limiter = RatelimitIO(backend=async_redis_client)

@async_limiter(LimitSpec(requests=10, seconds=60), unique_key="user:123")
async def fetch_data():
    return "Request succeeded!"

# Use the decorated function
await fetch_data()
```

### Using as a Synchronous Context Manager

```python
with limiter:
    limiter.wait("user:456", LimitSpec(requests=5, seconds=10))
```

### Using as a Asynchronous Context Manager

```python
async with limiter:
    await limiter.a_wait("user:456", LimitSpec(requests=5, seconds=10))
```

## License

[MIT](https://github.com/bagowix/ratelimit-io/blob/main/LICENSE)

## Contribution

Contributions are welcome! Follow the Contribution Guide for details.
