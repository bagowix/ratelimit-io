# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-21

### Added

- **`Key` templates for the decorator.** `@limiter(key=Key('user:{user_id}'))`
  fills the bucket key from each call's arguments with `str.format`, attributes
  and items included, as in `Key('search:{request.client.host}')`. A key per
  argument used to take a lambda that had to swallow every other argument,
  `key=lambda user_id, **_: f'user:{user_id}'`. The decorator checks that every
  field names a parameter when it is applied, and a field that is `None` or
  empty raises `ValueError` on the call: a lambda would count every such call
  in one `user:None` bucket.

### Changed

- **Key functions receive only the parameters they name.** A key function was
  called with every argument of the call, so the natural
  `key=lambda user_id: ...` passed import and failed on the first request with
  `TypeError: <lambda>() got an unexpected keyword argument`. It now receives
  `user_id` alone, and a required parameter the decorated function lacks
  raises `TypeError` when the decorator is applied, with or without
  `**kwargs`. Key functions that take `**kwargs` receive every argument, as
  before.
- **The decorator refuses a string key that reads as a template.**
  `key='user:{user_id}'` was a literal, one bucket for every call. It now
  raises `ValueError` when the decorator is applied and offers
  `Key('user:{user_id}')`. A decorator key that holds braces on purpose keeps
  its bucket as `Key('user:{{user_id}}')`.

## [1.0.0] - 2026-10-20

1.0 is a rewrite with a new API; the
[migration guide](https://bagowix.github.io/ratelimit-io/migration/) maps every
0.x name and setting to its replacement.

### Changed

- **One `RateLimiter` class with `acquire()` and `acquire_sync()`.** 0.x had
  `RatelimitIO.wait()` and `a_wait()`. The limiter now follows the
  `run`/`run_sync` pattern of pydantic-ai: `await acquire()` with a
  `redis.asyncio.Redis` client, `acquire_sync()` with a `redis.Redis` one, and
  a decorator for both. `LimitSpec` is now `Limit`, `RatelimitIOError` is
  `RateLimitError`, `RatelimitExceededError` is `RateLimitExceededError`.
- **`max_wait` replaces `is_incoming`, `max_wait_time` and the backoff
  settings.** `max_wait=0`, the default, refuses at once; a budget in seconds
  waits for a slot. One setting now says what two used to, and it can be
  overridden per call and per decorated function.
- **Python 3.11 or newer.** 3.8 to 3.10 are no longer supported; CI runs 3.11
  to 3.15.
- **Bucket names changed.** A bucket is now the key plus the algorithm, the
  limit and a `key_prefix`, so counters kept by 0.x are not read after the
  upgrade. They expire on their own within one period.
- **Releases are built and published by GitHub Actions** through PyPI trusted
  publishing, with PEP 740 attestations and no long-lived token. The toolchain
  moved from Poetry to uv and hatchling.

### Added

- **A choice of algorithm.** `Algorithm.SLIDING_WINDOW` never lets more than N
  requests into any period-long interval, which the fixed window cannot promise
  around its boundary. `Algorithm.GCRA` is a token bucket in constant memory.
  The fixed window stays the default.
- **Waiting requests reserve their slot.** One script call counts the request
  or, when the bucket is full, reserves the next free slot; the limiter then
  sleeps once. Waiters are served in arrival order across processes and never
  poll Redis or retry.
- **`retry_after` on every refusal.** `RateLimitExceededError` carries the
  `limit` that refused the request and the seconds until a request on that key
  can pass. Rounded up, it fills an HTTP `Retry-After` header.
- **Key functions.** The decorator's `key` can be a function that receives the
  call's arguments by name, defaults included, however the caller passed them,
  and returns the bucket key, e.g. `key=lambda user_id, **_: f'user:{user_id}'`.
- **`key_prefix`**, so applications that share a Redis server keep their
  buckets apart.
- **Typing.** The package ships `py.typed`, passes mypy, pyright and pyrefly in
  strict mode, and the decorator keeps the wrapped function's signature.
- **Documentation site** at <https://bagowix.github.io/ratelimit-io/>, with
  `llms.txt` for agents.

### Fixed

- **Outgoing waits could not outlast a 10-second window.** 0.x polled Redis
  every 10 to 100 ms and gave up after `max_wait_time`, 10 s by default, so a
  limit with a longer window always failed in outgoing mode, and every waiter
  kept hitting Redis meanwhile. The limiter now reserves the next slot and
  sleeps until it, and fails at once when that slot comes after the budget.
- **The decorator hid the rate limit error.** When the wait inside
  `@limiter(...)` ran out, 0.x raised a bare `RuntimeError` with the cause
  suppressed. The decorator now raises `RateLimitExceededError`.
- **Functions with the same name shared a limit.** The decorator keyed buckets
  by `__name__`, so `Users.get` and `Orders.get` counted together. Buckets now
  use the module and qualified name.
- **A positional `ip` argument disabled per-client limits.** 0.x read the key
  from `kwargs['ip']` only; called as `handler('203.0.113.7')`, every client
  fell into one shared `"unknown_key"` bucket. Keys are now named explicitly,
  and a key function sees arguments by name however they were passed.
- **Limits on one key collided.** `10/s` and `1000/h` on the same key counted
  in one counter. Each limit now has its own bucket.
- **A limiter-wide key was split per decorated function**, so a limiter meant
  to guard one external API allowed the full limit to every function using it.
- **Redis errors were reported as `ScriptLoadError`.** A refused connection
  surfaced as a script problem with HTTP status 500. Redis errors now propagate
  unchanged, and the script is reloaded transparently, even when a
  `SCRIPT FLUSH` lands between the reload and the retry.
- **Every call cost an extra round trip** to check that the script was loaded.
- **Invalid limits were accepted.** A negative period made the counter expire
  at once and disabled the limit; `requests=2.5` allowed three requests; a
  fractional period failed inside Redis. `Limit` now validates eagerly, and
  the limiter checks every key, limit and `max_wait` it is given.
- **Waits used the wall clock**, so a clock adjustment could cut a wait short
  or stretch it. The Redis server now works out each wait on its own clock,
  and the limiter sleeps it out in one call to `time.sleep` or `asyncio.sleep`,
  which run on the monotonic clock.
- **`asyncio.iscoroutinefunction` is deprecated in Python 3.14**; the decorator
  uses `inspect.iscoroutinefunction`.
- **The README named the wrong default mode**: it called outgoing mode the
  default, while 0.x defaulted to incoming.

### Removed

- `ScriptLoadError`: the limiter reloads its script itself.
- `async with limiter`: there was nothing to set up or tear down.
- `status_code` and `detail` on the errors: answer with `429` yourself.
- `backoff_start` and `backoff_max`: waits are exact now.
- The `ip` keyword argument convention and the `"unknown_key"` fallback bucket.

## [0.6.5] - 2025-01-22

### Changed

- README examples for outgoing request handling.

## [0.6.4] - 2025-01-22

### Changed

- README examples for outgoing request handling.
- Updated pre-commit hook versions.

## [0.6.3] - 2025-01-18

### Changed

- README examples for async context managers.

## [0.6.2] - 2025-01-18

### Added

- `RatelimitIO` works as an async context manager: `__aenter__` loads the Lua
  script into Redis.

## [0.6.1] - 2025-01-18

### Changed

- Version bump in `pyproject.toml` and README.

## [0.6.0] - 2025-01-18

### Added

- Error classes `RatelimitIOError`, `RatelimitExceededError` and
  `ScriptLoadError`.
- Logging when the Lua script fails to load.

### Changed

- Shared logic between the sync and async paths; more tests.

## [0.5.0] - 2025-01-16

### Added

- `is_incoming` inferred for bare decorators.
- Key priority `provided_key > unique_key > default_key > kwargs["ip"] >
  "unknown_key"`, with `async`/`sync` prefixes.

### Removed

- The `base_url` parameter, replaced by `default_key`.

### Changed

- PyPI builds run only for release commits.
- CONTRIBUTING describes the pre-commit hooks.

## [0.4.0] - 2025-01-16

### Fixed

- `default_key` defaults to `None`, so `kwargs["ip"]` is used when no key is
  given.
- Key handling in `wait` and `a_wait`, and `NoneType` errors when no
  `limit_spec` was given.

## [0.3.1] - 2025-01-15

### Fixed

- Python 3.8 and 3.9 compatibility of the type annotations.

### Changed

- README middleware examples for FastAPI and Django.

## [0.3.0] - 2025-01-15

### Added

- `RatelimitIOError`, modelled on `HTTPException`.
- The `is_incoming` flag and 429 handling examples for Flask, Django and
  FastAPI.

### Fixed

- `unique_key` fallback to `default_key`; script loading under concurrency.

## [0.2.5] - 2025-01-15

### Changed

- Downloads badge.

## [0.2.4] - 2025-01-15

### Changed

- README edits.

## [0.2.3] - 2025-01-15

### Added

- Package metadata in `pyproject.toml`.

## [0.2.0] - 2025-01-15

### Added

- Wheel builds in GitHub Actions.

## [0.1.1] - 2025-01-15

### Fixed

- License badge.

## [0.1.0] - 2025-01-15

- Initial release.

[Unreleased]: https://github.com/bagowix/ratelimit-io/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/bagowix/ratelimit-io/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/bagowix/ratelimit-io/compare/0.6.5...v1.0.0
[0.6.5]: https://github.com/bagowix/ratelimit-io/compare/0.6.4...0.6.5
[0.6.4]: https://github.com/bagowix/ratelimit-io/compare/0.6.3...0.6.4
[0.6.3]: https://github.com/bagowix/ratelimit-io/compare/0.6.2...0.6.3
[0.6.2]: https://github.com/bagowix/ratelimit-io/compare/0.6.1...0.6.2
[0.6.1]: https://github.com/bagowix/ratelimit-io/compare/0.6.0...0.6.1
[0.6.0]: https://github.com/bagowix/ratelimit-io/compare/0.5.0...0.6.0
[0.5.0]: https://github.com/bagowix/ratelimit-io/compare/0.4.0...0.5.0
[0.4.0]: https://github.com/bagowix/ratelimit-io/compare/0.3.1...0.4.0
[0.3.1]: https://github.com/bagowix/ratelimit-io/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/bagowix/ratelimit-io/compare/0.2.5...0.3.0
[0.2.5]: https://github.com/bagowix/ratelimit-io/compare/0.2.4...0.2.5
[0.2.4]: https://github.com/bagowix/ratelimit-io/compare/0.2.3...0.2.4
[0.2.3]: https://github.com/bagowix/ratelimit-io/compare/0.2.0...0.2.3
[0.2.0]: https://github.com/bagowix/ratelimit-io/compare/0.1.1...0.2.0
[0.1.1]: https://github.com/bagowix/ratelimit-io/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/bagowix/ratelimit-io/releases/tag/0.1.0
