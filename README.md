# Ratelimit-IO

A Python library for rate limiting, designed to handle both incoming and outgoing requests efficiently. Supports both synchronous and asynchronous paradigms. Powered by Redis, this library provides decorators and easy integration with APIs to manage request limits with precision.

#### Project Information
[![Tests & Lint](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml/badge.svg)](https://github.com/bagowix/ratelimit-io/actions/workflows/actions.yml)
[![image](https://img.shields.io/pypi/v/ratelimit-io/0.6.4.svg)](https://pypi.python.org/pypi/ratelimit-io)
[![Test Coverage](https://img.shields.io/badge/dynamic/json?color=blueviolet&label=coverage&query=%24.totals.percent_covered_display&suffix=%25&url=https%3A%2F%2Fraw.githubusercontent.com%2Fbagowix%2Fratelimit-io%2Fmain%2Fcoverage.json)](https://github.com/bagowix/ratelimit-io/blob/main/coverage.json)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ratelimit-io)](https://pypi.org/project/ratelimit-io/)
[![License](https://img.shields.io/pypi/l/ratelimit-io)](LICENSE)
[![Downloads](https://pepy.tech/badge/ratelimit-io)](https://pepy.tech/project/ratelimit-io)
[![Formatter](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

## Features

- **Incoming and Outgoing Request Management**:
  - Handle inbound limits (e.g., API requests) with immediate error raising.
  - Manage outbound limits (e.g., client requests to external APIs) with intelligent waiting.
- **Synchronous and Asynchronous Support**:
  - Seamlessly integrate with both blocking and async applications.
- **Asynchronous Context Manager**:
  - Use `async with` for automatic Lua script loading and resource management.
- **Customizable Rate Limits**:
  - Define limits by requests, time periods, or custom keys.
- **Redis Backend**:
  - Leverages Redis for fast and scalable rate limiting.
- **Decorators**:
  - Apply rate limits easily to functions or methods.
- **Automatic Error Handling**:
  - Easily manage 429 Too Many Requests errors in popular frameworks like Flask, Django, and FastAPI.
- **Granular Key Management**:
  - Priority-based key resolution for efficient bucket management.
- **Ease of Use**:
  - Simple and intuitive integration into Python applications.

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
limiter = RatelimitIO(
    backend=redis_client,
    default_limit=LimitSpec(requests=10, seconds=60),
    default_key="global_limit",
)


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
async_limiter = RatelimitIO(
    backend=async_redis_client,
    default_limit=LimitSpec(requests=10, seconds=60),
    default_key="global_limit",
)


@async_limiter
async def fetch_data():
  return "Request succeeded!"


# Use the decorated function
await fetch_data()
```

### Asynchronous Context Manager

Simplify usage with the asynchronous context manager:

```python
from ratelimit_io import RatelimitIO, LimitSpec
from redis.asyncio import Redis as AsyncRedis

async def main():
    redis_client = AsyncRedis(host="localhost", port=6379)

    async with RatelimitIO(
        backend=redis_client,
        default_limit=LimitSpec(requests=5, seconds=10),
    ) as limiter:
        # Lua script is automatically loaded here
        await limiter.a_wait("test_key")
        print("Request processed within limit!")

# The Redis connection remains open after exiting the context
```

### Incoming vs. Outgoing Request Handling (`is_incoming`)

- The `default_key` or a dynamically generated key (e.g., based on `unique_key` or `kwargs["ip"]`) determines the rate limit bucket.
- When `is_incoming=True`, the rate limiter will immediately raise a `RatelimitIOError` when limits are exceeded.
- When `is_incoming=False` (default), the rate limiter will wait until a slot becomes available.

```python
# Incoming request example (throws an error on limit breach)
limiter = RatelimitIO(backend=redis_client, is_incoming=True)

@limiter(limit_spec=LimitSpec(requests=5, seconds=10))
def fetch_data():
    return "Request succeeded!"

# Outgoing request example (waits if limits are exceeded)
outgoing_limiter = RatelimitIO(
    backend=redis_client,
    default_key="https://api.example.com",
    default_limit=LimitSpec(requests=5, seconds=10),
)


def fetch_data_outgoing():
    async with httpx.AsyncClient() as client:
        await outgoing_limiter.a_wait("outgoing_request")
        response = await client.get("https://api.example.com")
        return response.json()
```

## Dynamic `is_incoming` Detection

Automatically determines request type (incoming or outgoing) based on the context. Incoming requests (default) raise `RatelimitIOError` if limits are exceeded, while outgoing requests wait for a slot.

Examples:

```python
# Default behavior (is_incoming=True)
@limiter
def incoming_request():
    return "Handled incoming request!"

for _ in range(5):
    incoming_request()

# Raises RatelimitIOError after 5 requests
incoming_request()


# Outgoing request handling
limiter.is_incoming = False

for _ in range(5):
    limiter.wait("outgoing_request", LimitSpec(requests=5, seconds=1))

# Waits for a slot to become available
limiter.wait("outgoing_request", LimitSpec(requests=5, seconds=1))
```

## Error Handling for 429 Responses in Frameworks

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
  default_limit=LimitSpec(requests=5, seconds=1),
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
  default_limit=LimitSpec(requests=5, seconds=1),
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

## Key Handling Priority

The rate limiter determines the key for requests in the following priority:

1. `provided_key` (directly passed to `wait`, `a_wait`, or decorator).
2. `unique_key` (e.g., from a decorator argument).
3. `default_key` (set during `RatelimitIO` initialization).
4. `kwargs.get("ip")` (from additional arguments passed to the decorated function).
5. `"unknown_key"` (fallback if no other key is found).

This flexible approach ensures minimal configuration while maintaining granular control when needed.

## License

[MIT](https://github.com/bagowix/ratelimit-io/blob/main/LICENSE)

## Contribution

Contributions are welcome! Follow the Contribution Guide for details.
