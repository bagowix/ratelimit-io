# Frameworks

ratelimit-io has no framework integrations to install: a limiter is called
from a dependency, a middleware or a decorator, and `RateLimitExceededError`
becomes a `429` with a `Retry-After` header. `retry_after` is a float, and the
header takes whole seconds, so round it up.

## FastAPI

A dependency limits every route that declares it, and an exception handler
turns refusals into responses:

```python
import math

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from ratelimit_io import Limit, RateLimiter, RateLimitExceededError

app = FastAPI()
limiter = RateLimiter(Redis(), limit=Limit(100, minutes=1))


@app.exception_handler(RateLimitExceededError)
async def too_many_requests(request: Request, error: RateLimitExceededError) -> JSONResponse:
    return JSONResponse(
        {'detail': 'Too many requests'},
        status_code=429,
        headers={'Retry-After': str(math.ceil(error.retry_after))},
    )


async def rate_limit(request: Request) -> None:
    if request.client is None:
        raise HTTPException(500, 'no client address to rate limit by')

    await limiter.acquire(f'{request.url.path}:{request.client.host}')


@app.get('/items', dependencies=[Depends(rate_limit)])
async def list_items() -> list[str]:
    return []
```

`request.client` is `None` when the server sees no peer address, behind a Unix
socket for example. Key on the address your proxy forwards then: a placeholder
such as `'unknown'` would put every such client in one bucket.

The decorator works on routes as well. It keeps the endpoint's signature, so
FastAPI still sees the parameters, and a key function receives them by name:

```python
@app.get('/search')
@limiter(key=lambda request, **_: f'search:{request.client.host}')
async def search(request: Request, q: str) -> list[str]:
    return []
```

Put `@app.get` above the limiter, so the route registers the limited function.

## Litestar

A guard runs before the handler, and an exception handler answers the refusal:

```python
import math

from litestar import Litestar, Request, Response, get
from litestar.connection import ASGIConnection
from litestar.exceptions import InternalServerException
from litestar.handlers.base import BaseRouteHandler
from redis.asyncio import Redis

from ratelimit_io import Limit, RateLimiter, RateLimitExceededError

limiter = RateLimiter(Redis(), limit=Limit(100, minutes=1))


async def rate_limit(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    if connection.client is None:
        raise InternalServerException('no client address to rate limit by')

    await limiter.acquire(f'{connection.url.path}:{connection.client.host}')


def too_many_requests(request: Request, error: RateLimitExceededError) -> Response[dict[str, str]]:
    return Response(
        {'detail': 'Too many requests'},
        status_code=429,
        headers={'Retry-After': str(math.ceil(error.retry_after))},
    )


@get('/items', guards=[rate_limit])
async def list_items() -> list[str]:
    return []


app = Litestar(
    route_handlers=[list_items],
    exception_handlers={RateLimitExceededError: too_many_requests},
)
```

## Django

Django views are sync, so the limiter takes a `redis.Redis` client and calls
`acquire_sync()`. A middleware covers every view:

```python
import math

from django.http import HttpRequest, HttpResponse
from redis import Redis

from ratelimit_io import Limit, RateLimiter, RateLimitExceededError

limiter = RateLimiter(Redis(), limit=Limit(100, minutes=1))


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            limiter.acquire_sync(request.META['REMOTE_ADDR'])
        except RateLimitExceededError as error:
            response = HttpResponse('Too many requests', status=429)
            response['Retry-After'] = str(math.ceil(error.retry_after))
            return response

        return self.get_response(request)
```

Behind a proxy, key on the client address your proxy forwards rather than on
`REMOTE_ADDR`.

## Flask

An error handler plus the decorator on a view. Flask passes URL parameters as
keyword arguments, so the key function swallows them with `**_`:

```python
import math

from flask import Flask, request
from redis import Redis

from ratelimit_io import Limit, RateLimiter, RateLimitExceededError

app = Flask(__name__)
limiter = RateLimiter(Redis(), limit=Limit(100, minutes=1))


@app.errorhandler(RateLimitExceededError)
def too_many_requests(error: RateLimitExceededError):
    return 'Too many requests', 429, {'Retry-After': str(math.ceil(error.retry_after))}


@app.get('/items/<int:item_id>')
@limiter(key=lambda **_: f'items:{request.remote_addr}')
def get_item(item_id: int) -> str:
    return str(item_id)
```

## Outgoing calls with httpx

For a client of someone else's API, a limiter-wide key and a wait budget keep
every call under the provider's quota:

```python
import httpx
from redis.asyncio import Redis

from ratelimit_io import Algorithm, Limit, RateLimiter

github = RateLimiter(
    Redis(),
    limit=Limit(5000, hours=1),
    key='github',
    algorithm=Algorithm.SLIDING_WINDOW,
    max_wait=30,
)


@github
async def fetch_repo(client: httpx.AsyncClient, name: str) -> dict[str, object]:
    response = await client.get(f'https://api.github.com/repos/{name}')
    response.raise_for_status()
    return response.json()
```

The sliding window never lets more than 5000 calls into any hour, which a fixed
window cannot promise around its boundary. See [Algorithms](guides/algorithms.md).
