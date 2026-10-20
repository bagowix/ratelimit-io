# Migrating from 0.x

1.0 is a breaking release. It needs Python 3.11 or newer, renames the public
names, and replaces two settings with one. The library's behaviour changed in
places where 0.x was wrong; those changes are listed under
[Behaviour](#behaviour).

## Names

| 0.x | 1.0 |
|---|---|
| `from ratelimit_io.rate_limit import ...` | `from ratelimit_io import ...` |
| `RatelimitIO(backend, ...)` | `RateLimiter(client, ...)` |
| `LimitSpec(5, seconds=1)` | `Limit(5, seconds=1)` |
| `RatelimitIOError` | `RateLimitError` |
| `RatelimitExceededError` | `RateLimitExceededError` |
| `ScriptLoadError` | removed: the limiter reloads its script itself, and Redis errors propagate unchanged |
| `limiter.wait(key, spec)` | `limiter.acquire_sync(key, limit=spec)` |
| `await limiter.a_wait(key, spec)` | `await limiter.acquire(key, limit=spec)` |
| `async with limiter:` | removed: there is nothing to set up or tear down |

## Settings

| 0.x | 1.0 |
|---|---|
| `default_limit=` | `limit=` |
| `default_key=` | `key=` |
| `is_incoming=True` | `max_wait=0`, the default |
| `is_incoming=False` | `max_wait=10`, or any other budget in seconds |
| `wait(..., max_wait_time=)` | `acquire_sync(..., max_wait=)` |
| `backoff_start=`, `backoff_max=` | removed: a waiting request reserves its slot and sleeps until it |
| decorator `unique_key='x'` | decorator `key='x'` |
| `kwargs['ip']` picked up as the key | `key=lambda ip, **_: ip` |

## Behaviour

- **Refusals carry `retry_after`.** `RateLimitExceededError` has the `limit`
  that refused the request and `retry_after` in seconds. The HTTP-flavoured
  `status_code` and `detail` attributes are gone; answer with `429` yourself.
- **The decorator raises `RateLimitExceededError`.** 0.x turned an exhausted
  wait inside `@limiter(...)` into a bare `RuntimeError`.
- **A waiting request reserves its slot.** 0.x polled Redis until a slot freed
  up; 1.0 reserves the next free slot in one round trip and sleeps until it,
  serving waiters in arrival order. A wait cancelled during its sleep still
  uses its slot.
- **Functions get their own bucket by qualified name.** 0.x used `__name__`,
  so two methods called `get` on different classes shared one limit. 0.x also
  gave sync and async functions separate buckets for the same key.
- **The limiter's `key` is shared by the functions it decorates.** In 0.x a
  `default_key` was still split per function.
- **`ip` is no longer magic.** 0.x read `kwargs['ip']` and silently fell back
  to one shared `"unknown_key"` bucket when `ip` was passed positionally. Name
  the key explicitly.
- **No silent fallback key.** `acquire()` without a key on a limiter without
  one raises `ValueError`. 0.x counted such calls in `"unknown_key"`.
- **Redis errors propagate.** 0.x turned every Redis failure, a refused
  connection included, into `ScriptLoadError`.
- **Validation is strict.** `Limit` refuses negative, infinite and fractional
  request counts and periods under a millisecond. Keys must be non-empty
  strings, `max_wait` a number of seconds. A mismatch between the client and
  the call style (`acquire()` on a sync client, a coroutine function decorated
  on a sync client) raises `TypeError` with the fix in the message.
- **Import from `ratelimit_io` only.** The modules inside the package are
  private and may move between releases.

## Buckets start empty

The bucket names changed: they now carry the algorithm and the limit, so
layered limits on one key no longer collide. Counters from 0.x are not read
after the upgrade and expire on their own within one period.
