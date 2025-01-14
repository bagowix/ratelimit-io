# RatelimitIO

A Python library for rate limiting, built to handle both incoming and outgoing requests efficiently. Supports both synchronous and asynchronous paradigms. Powered by Redis, this library provides decorators, context managers, and easy integration with APIs to manage request limits with precision.

#### Project Information
[![Tests & Lint](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml/badge.svg)](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml)
[![Test Coverage](https://img.shields.io/badge/dynamic/json?color=blueviolet&label=coverage&query=%24.totals.percent_covered_display&suffix=%25&url=https%3A%2F%2Fraw.githubusercontent.com%2Fbagowix%2Fratelimit-io%2Fmain%2Fcoverage.json)](https://github.com/bagowix/ratelimit-io/blob/main/coverage.json)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ratelimit-io)](https://pypi.org/project/ratelimit-io/)
[![License](https://img.shields.io/pypi/l/ratelimit-io)](LICENSE)

---

## Features

- **Incoming and Outgoing Support**: Effectively handles limits for both inbound
- **Synchronous and Asynchronous Support**: Works seamlessly in both paradigms.
- **Redis Backend**: Leverages Redis for fast and scalable rate limiting.
- **Flexible API**:
  - Use as a **decorator** for methods or functions.
  - Use as a **context manager** for precise control over request flows.
  - Integrate directly into API clients, middlewares, or custom request handlers.
- **Customizable Rate Limits**: Specify limits per key, time period, and requests.
- **Robust Lua Script**: Ensures efficient and atomic rate limiting logic for high-concurrency use cases.
- **Ease of Use**: Simple and intuitive integration into Python applications.

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

@limiter(LimitSpec(requests=10, seconds=60), unique_key="user:123")  # unique_key is optional
def fetch_data():
    return "Request succeeded!"

# Use the decorated function
fetch_data()
```

**Note**: The `unique_key` parameter is `optional`. If not provided, the `IP address` (or another default identifier, based on your application logic) will be used to apply rate limiting.

### Using as a Asynchronous Decorator

```python
from ratelimit_io import RatelimitIO, LimitSpec
from redis.asyncio import Redis as AsyncRedis

async_redis_client = AsyncRedis(host="localhost", port=6379)
async_limiter = RatelimitIO(backend=async_redis_client)

@async_limiter(LimitSpec(requests=10, seconds=60), unique_key="user:123")  # unique_key is optional
async def fetch_data():
    return "Request succeeded!"

# Use the decorated function
await fetch_data()
```

**Note**: Similar to the synchronous decorator, the `unique_key` is `optional`. If omitted, the `IP address` (or a default identifier) will be used.

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
