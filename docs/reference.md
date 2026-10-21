# API reference

Everything below is importable from the top-level `ratelimit_io` package. The
modules inside it are private and may move between releases.

## `RateLimiter`

```python
RateLimiter(client, *, limit=None, key=None, algorithm=Algorithm.FIXED_WINDOW,
            max_wait=0, key_prefix='ratelimit_io')
```

A distributed rate limiter on Redis.

- **`client`**: a `redis.asyncio.Redis` for `acquire()` and coroutine
  functions, or a `redis.Redis` for `acquire_sync()` and plain functions.
  Sentinel's `master_for()` returns such a client. Anything else raises
  `TypeError`.
- **`limit`**: the default `Limit` of calls that name none.
- **`key`**: the default bucket key of calls that name none.
- **`algorithm`**: see [`Algorithm`](#algorithm).
- **`max_wait`**: seconds a request may wait for a slot. `0` fails at once;
  `math.inf` waits as long as it takes.
- **`key_prefix`**: the namespace of every bucket in Redis.

Raises `TypeError` for an option of the wrong type, and `ValueError` for an
empty `key` or `key_prefix`, a negative or NaN `max_wait`, or an unknown
algorithm.

### `await acquire(key=None, *, limit=None, max_wait=None)`

Takes one slot from the bucket of `key` through an async client. When the
bucket is full and its next free slot is at most `max_wait` seconds away, the
request reserves that slot and sleeps until it; otherwise it raises
`RateLimitExceededError` at once. Waiting requests are served in arrival order
across processes. See [Waiting for a slot](guides/waiting.md).

Raises `TypeError` on a sync client or for an argument of the wrong type, and
`ValueError` when no key or no limit is given and the limiter has none.

### `acquire_sync(key=None, *, limit=None, max_wait=None)`

The blocking twin of `acquire()`, through a sync client.

### `@limiter` / `@limiter(*, key=None, limit=None, max_wait=None)`

Rate limits every call of the decorated function, recursive calls included.
Coroutine functions take their slot with `acquire()`, plain functions with
`acquire_sync()`. The wrapper keeps the function's signature and metadata.

`limiter(func, *, key=None, limit=None, max_wait=None)` does the same for a
function defined elsewhere, such as a method of a third-party client.

The bucket key of a call is the decorator's `key`, else the limiter's `key`,
else the function's `module.qualname`. The decorator's `key` is a string, a
[`Key`](#key) template, or a key function that receives the arguments it names,
bound by name with defaults included, and returns the key. A key function that
takes `**kwargs` receives every argument. See
[Keys and buckets](guides/keys.md).

Raises `TypeError` when the function's nature does not match the client, for
a `staticmethod` or `classmethod` object (put `@limiter` below them), a
generator function, anything not callable, a `Key` field or a required key
function parameter that names no parameter of the function, or an option of
the wrong type. Raises `ValueError` for an empty `key`, a string `key` that
reads as a template (pass a `Key`), a negative `max_wait`, or when no limit is
given and the limiter has none. On the call, a key function that returns an
empty string and a `Key` field that is `None` or empty raise `ValueError`, and
a key function that returns anything but a string raises `TypeError`.

## `Key`

```python
Key(template)
```

Frozen dataclass: a decorator key that `str.format` fills from the arguments
of each call, as in `@limiter(key=Key('user:{user_id}'))`. A field starts with
the name of a parameter of the decorated function and may go on to attributes
and items: `{request.client.host}`, `{headers[x-api-key]}`. A plain `str` key
is never formatted. See [`Key` templates](guides/keys.md#key-templates).

Doubled braces stay literal: `Key('{{tag}}:{user_id}')` fills `{tag}:42`.

Raises `TypeError` when `template` is not a string, and `ValueError` when it is
empty or malformed, or has a positional field such as `{}` or `{0}`, an unknown
conversion, or a field inside a format spec.

## `Limit`

```python
Limit(requests, *, seconds=0, minutes=0, hours=0)
```

Frozen dataclass: `requests` per period of `seconds + minutes + hours`. The
period may be fractional and is enforced to the millisecond. Limits that allow
the same requests per the same period are equal and hash alike:
`Limit(1, minutes=1) == Limit(1, seconds=60)`.

- **`total_seconds() -> float`**: the period in seconds.
- **`period_ms() -> int`**: the period in whole milliseconds.
- **`str(limit)`**: `'100/60s'`, with the period as enforced.

`requests` can be any integer type, numpy's included, and is stored as an
`int`. Raises `TypeError` when `requests` is not an integer or a period part is
not a number (a bool is neither), and `ValueError` when `requests` is not
positive, a period part is negative or not finite, or the period is shorter
than a millisecond.

## `Algorithm`

`StrEnum` of the counting algorithms. See [Algorithms](guides/algorithms.md).

- `Algorithm.FIXED_WINDOW = 'fixed_window'`, the default.
- `Algorithm.SLIDING_WINDOW = 'sliding_window'`.
- `Algorithm.GCRA = 'gcra'`.

## `RateLimitExceededError`

```python
RateLimitExceededError(limit, retry_after)
```

Raised when a request is refused: the next free slot is further away than the
request may wait.

- **`limit: Limit`**: the limit that refused the request.
- **`retry_after: float`**: seconds until a request on the same key can pass.
  Round it up for an HTTP `Retry-After` header.

Subclass of `RateLimitError`. It survives pickling, so it can cross process
boundaries.

## `RateLimitError`

Base class of every error raised by ratelimit-io. Invalid arguments raise the
built-in `TypeError` and `ValueError`, and Redis failures raise redis-py's own
exceptions unchanged.

## `VERSION` / `__version__`

The installed version, as a string.
