# RatelimitIO

A Python library for rate limiting, designed to handle both incoming and outgoing requests efficiently. Supports both synchronous and asynchronous paradigms. Powered by Redis, this library provides decorators, context managers, and easy integration with APIs to manage request limits with precision.

#### Project Information
[![Tests & Lint](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml/badge.svg)](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml)
[![Test Coverage](https://img.shields.io/badge/dynamic/json?color=blueviolet&label=coverage&query=%24.totals.percent_covered_display&suffix=%25&url=https%3A%2F%2Fraw.githubusercontent.com%2Fbagowix%2Fratelimit-io%2Fmain%2Fcoverage.json)](https://github.com/bagowix/ratelimit-io/blob/main/coverage.json)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ratelimit-io)](https://pypi.org/project/ratelimit-io/)
[![License](https://img.shields.io/pypi/l/ratelimit-io)](LICENSE)
[![PyPI Downloads](https://img.shields.io/pypi/dm/ratelimit-io)](https://pypi.org/project/ratelimit-io/)

---

## Features

- **Incoming and Outgoing Support**: Effectively handles limits for both inbound (e.g., API requests) and outbound (e.g., client requests to external APIs) traffic.
- **Synchronous and Asynchronous Support**: Works seamlessly in both paradigms.
- **Redis Backend**: Leverages Redis for fast and scalable rate limiting.
- **Flexible API**:
  - Use as a **decorator** for methods or functions.
  - Use as a **context manager** for precise control over request flows.
  - Integrate directly into API clients, middlewares, or custom request handlers.
- **Customizable Rate Limits**: Specify limits per key, time period, and requests.
- **Robust Lua Script**: Ensures efficient and atomic rate limiting logic for high-concurrency use cases.
- **Automatic Error Handling**: Easily manage 429 Too Many Requests errors in popular frameworks like Flask, Django, and FastAPI.
- **Support for Incoming Request Behavior**: Use the `is_incoming` flag to distinguish between incoming requests (throwing errors immediately) and outgoing requests (waiting for available slots).
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
limiter = RatelimitIO(backend=redis_client, base_limit=LimitSpec(requests=10, seconds=60))

@limiter
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
async_limiter = RatelimitIO(backend=async_redis_client, base_limit=LimitSpec(requests=10, seconds=60))

@async_limiter
async def fetch_data():
    return "Request succeeded!"

# Use the decorated function
await fetch_data()
```

### Incoming vs. Outgoing Request Handling (`is_incoming`)

- When `is_incoming=True`, the rate limiter will immediately raise a `RatelimitIOError` when limits are exceeded.
- When `is_incoming=False` (default), the rate limiter will wait until a slot becomes available.

```python
# Incoming request example (throws an error on limit breach)
limiter = RatelimitIO(backend=redis_client, is_incoming=True)

@limiter(LimitSpec(requests=5, seconds=10))
def fetch_data():
    return "Request succeeded!"

# Outgoing request example (waits if limits are exceeded)
outgoing_limiter = RatelimitIO(backend=redis_client)

@outgoing_limiter(LimitSpec(requests=5, seconds=10))
def fetch_data_outgoing():
    return "Request succeeded!"
```

### Using as a Synchronous Context Manager

```python
from ratelimit_io import RatelimitIO, LimitSpec
from redis import Redis

redis_client = Redis(host="localhost", port=6379)
limiter = RatelimitIO(backend=redis_client)

with limiter:
    limiter.wait("user:456", LimitSpec(requests=5, seconds=10))
```

### Using as a Asynchronous Context Manager

```python
from ratelimit_io import RatelimitIO, LimitSpec
from redis.asyncio import Redis as AsyncRedis

async_redis_client = AsyncRedis(host="localhost", port=6379)
async_limiter = RatelimitIO(backend=async_redis_client)

async with async_limiter:
    await async_limiter.a_wait("user:456", LimitSpec(requests=5, seconds=10))
```

## Error Handling for 429 Responses

### FastAPI Example

```python
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from ratelimit_io import RatelimitIO, RatelimitIOError, LimitSpec
from redis.asyncio import Redis as AsyncRedis

app = FastAPI()
redis_client = AsyncRedis(host="localhost", port=6379)
limiter = RatelimitIO(
    backend=redis_client,
    base_limit=LimitSpec(requests=5, seconds=1),
    is_incoming=True
)

@app.middleware("http")
async def ratelimit_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except RatelimitIOError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

@app.get("/fetch")
@limit
async def fetch_data():
    return {"message": "Request succeeded!"}
```

### Django Middleware Example

```python
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from ratelimit_io import RatelimitIO, LimitSpec, RatelimitIOError
from redis import Redis
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


redis = Redis("localhost", port=6379)
limit = RatelimitIO(
    backend=redis,
    base_limit=LimitSpec(requests=5, seconds=1),
    is_incoming=True,
)


class RatelimitMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if isinstance(exception, RatelimitIOError):
            return JsonResponse(
                {"detail": exception.detail},
                status=exception.status_code,
            )
        return None


class Foo(APIView):
    permission_classes = ()

    @limit
    def get(self, request, *args, **kwargs):
        return Response(data={"message": "ok"}, status=status.HTTP_200_OK)

```

### Flask Example

```python
from flask import Flask, jsonify
from ratelimit_io import RatelimitIO, RatelimitIOError, LimitSpec
from redis import Redis

app = Flask(__name__)
redis_client = Redis(host="localhost", port=6379)
limiter = RatelimitIO(backend=redis_client, is_incoming=True)

@app.errorhandler(RatelimitIOError)
def handle_ratelimit_error(error):
    return jsonify({"error": error.detail}), error.status_code

@app.route("/fetch")
@limiter
def fetch_data():
    return jsonify({"message": "Request succeeded!"})
```

## License

[MIT](https://github.com/bagowix/ratelimit-io/blob/main/LICENSE)

## Contribution

Contributions are welcome! Follow the Contribution Guide for details.
