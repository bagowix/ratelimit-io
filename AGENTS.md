# AGENTS.md

Distributed rate limiting for Python on Redis: fixed window, sliding window and
GCRA as atomic Lua scripts, one `RateLimiter` class for async and sync code, for
incoming requests a server sheds and outgoing requests a client waits for.
People put a rate limiter in front of their APIs and their spending, so the bar
for correctness, simplicity and dependency hygiene is higher than usual.

PyPI name `ratelimit-io`, import `ratelimit_io`.

## Decision-making principles

- Start from the problem: understand it first, pick tools second.
- Occam's razor: no new entities or abstractions without necessity.
- Never break existing functionality while making a change.
- A solution must be simple, reliable and readable without extra explanation.
- Minimise cognitive load, for the human and for the next agent.
- The upsides of a decision must heavily outweigh the downsides.
- Write code, docstrings and docs in English.

## Technology

- **Python 3.11+**; CI runs 3.11 to 3.15.
- **redis-py ≥ 5.0.1** is the only runtime dependency. The floor is a
  compatibility promise, guarded by the `deps-min` CI job.
- **uv** is the package manager. **hatchling** is the build backend; the
  version is static in `ratelimit_io/version.py`, bumped by hand on release and
  exposed as `ratelimit_io.__version__`.
- **ruff** (`select = ["ALL"]`, line length 100, single quotes) formats and
  lints. **mypy, pyright and pyrefly** check types in strict mode.
- **pytest** with pytest-asyncio (strict mode), pytest-xdist, pytest-cov,
  pytest-mock, hypothesis and fakeredis. Coverage gate: 100% branches.
- **zizmor** audits the workflows; **griffe** diffs the public API against the
  latest release tag. **Zensical** builds the docs site.

## Commands

```bash
uv sync                          # venv + dev dependencies
uv run prek install              # one-time: git hooks
uv run pytest --cov              # tests on fakeredis, 100% coverage
RATELIMIT_IO_TEST_REDIS_URL=redis://localhost:6379/0 uv run pytest   # real server, adds the concurrency tests
uv run pytest tests/test_limiter.py::test__acquire_sync__over_limit__raises_with_retry_after -n 0
uv run ruff format --check && uv run ruff check
uv run mypy && uv run pyright && uv run pyrefly check
uv run zizmor .github/
uv run zensical build --strict && uv run python scripts/mirror_markdown.py
uv run python scripts/build_llms_full.py   # after editing any page in docs/
```

`mypy` runs bare: its file list lives in `[tool.mypy] files`.

## Architecture

The public API is what `ratelimit_io/__init__.py` exports. Every other module
except `version.py` is private, so it can be reorganised without a major
release.

- `_limit.py`: `Limit`, a frozen dataclass validated in `__post_init__`. It
  compares and hashes by `(requests, period_ms())`, the identity its bucket is
  counted under.
- `_algorithm.py`: the `Algorithm` StrEnum. `_scripts.py`: one Lua script per
  algorithm. Every script takes `KEYS[1]` (bucket), `ARGV[1]` (requests),
  `ARGV[2]` (period in ms), `ARGV[3]` (how many ms the request may wait,
  `inf` for no limit) and `ARGV[4]` (a member unique to the request, used by
  the sliding window). It reserves the earliest free slot and returns the ms until
  it, `0` meaning now. When that slot is further away than the request may
  wait, it records nothing and returns the negated wait, `-1` or less.
- `_limiter.py`: `RateLimiter`. `acquire()` and `acquire_sync()` are twin
  paths: a change to one is mirrored in the other and tested on both. The
  decorator dispatches on `inspect.iscoroutinefunction` and checks at
  decoration time that the client matches the function. A `Key` template and
  a key function see the call's arguments bound by name through
  `inspect.signature().bind()`; a key function gets only the parameters it
  names, or all of them when it takes `**kwargs`.
- `_key.py`: `Key`, a frozen dataclass holding a `str.format` template, and
  the formatter that fills it. Every field must name a parameter of the
  decorated function (checked at decoration), and a field that is `None` or
  empty raises: it would put unrelated calls in one bucket.
- `_errors.py`: `RateLimitError` and `RateLimitExceededError(limit, retry_after)`.
- `version.py`: `VERSION`, the one place the package version is written.

## Invariants

- **All counting happens in one Lua script per request.** Never split a
  decision into several commands: the script is what makes the limit atomic
  across processes.
- **Time comes from Redis.** Every script reads the server's `TIME` in whole
  microseconds; the client never reads a clock. Expiry only collects idle
  buckets: every decision reads the stored times, so a bucket that lost its TTL
  still counts correctly.
- **Scripts count in whole numbers.** GCRA keeps its TAT as a backlog relative
  to the moment it was written, in units of 1/limit microseconds, so a request
  adds exactly one period. A fractional emission interval lets `limit` of them
  add up past the period and refuses the last request of a burst; an absolute
  TAT near 2^51 microseconds loses up to a quarter of a microsecond on every
  addition. The numbers stay exact while period × limit stays under 2^53
  microseconds.
- **A refused request is never recorded**, and a refusal always reports a
  positive wait.
- **A bucket is `{key_prefix}:{algorithm}:{requests}/{period_ms}ms:{sha256(key)}`.**
  Raw keys never reach Redis. Changing the format resets every counter in
  production, so it is a breaking change.
- **Scripts run as EVALSHA with an EVAL fallback** on `NoScriptError`. Do not
  switch to redis-py's `register_script`: its SCRIPT LOAD + EVALSHA retry
  leaves room for a concurrent `SCRIPT FLUSH`. The tests run the fallback
  against a script the server has never cached; they never flush the server.
- **Waiting reserves.** One script call counts the request or reserves its
  future slot; the client then sleeps once and returns. Never add a retry
  loop: waiters that sleep until a slot frees and then retry all wake at the
  same moment, cost N² script calls for N waiters and exhaust the connection
  pool. Waiters are served in arrival order.

## Code style

- Separate logical blocks inside a function with blank lines: guards, setup,
  the main action, the return. Dense walls of statements are unreadable.
- Keyword-only arguments for options; the key is the only positional argument
  of `acquire()` / `acquire_sync()`.
- Modern typing (`X | None`, `list[str]`); `typing.Optional`/`Union` are banned
  by ruff.
- No fallback values and no `a or b` chains for required data: resolve
  defaults explicitly against `None`. An empty key is an error, never a reason
  to fall back to a shared bucket.
- Comments explain what the code cannot: a non-obvious decision, a trap. A
  `noqa` or `type: ignore` carries its reason.

## Error handling

- Fail fast on invalid input with `TypeError` / `ValueError` and a message that
  names the fix.
- Redis errors propagate unchanged. Do not wrap them in library errors and do
  not add fail-open behaviour without an explicit request: a rate limit can be a
  security control.
- `RateLimitExceededError` passes both constructor arguments to
  `Exception.__init__` so it survives pickling; keep it that way.

## Tests

- pytest functions, no classes. Names: `test__unit__state__expected`, e.g.
  `test__acquire_sync__over_limit__raises_with_retry_after`.
- Arrange, act and assert separated by blank lines; one behaviour per test.
- Tests isolate by a unique `key_prefix` (the `prefix` / `make_limiter`
  fixtures in `tests/conftest.py`) and never flush the server.
- Async tests carry `@pytest.mark.asyncio`; async fixtures use
  `@pytest_asyncio.fixture`.
- Tests that prove atomicity under concurrency are marked
  `requires_real_redis`; fakeredis would pass them even with a broken script.
- `tests/typing_surface.py` is type-checked, never run: extend it when the
  public typing changes.
- To see the sleeps a reservation causes without waiting for them, patch
  `ratelimit_io._limiter.time` (or `.asyncio`) with a recorder; the server
  still decides every slot.
- `tests/test_scripts.py` runs each script on a clock the test sets (`TIME`
  becomes `ARGV[5..6]`, and `PEXPIRE` writes to a log). Pin a script's
  arithmetic there, to the microsecond: a test that waits in real time cannot
  resolve a millisecond.

## Definition of done

- Tests first; a bug fix starts with a test that reproduces it.
- Coverage stays at 100%; ruff, mypy, pyright and pyrefly are clean.
- The suite passes against a real Redis as well as fakeredis.
- User-facing changes update `docs/`, regenerate `docs/llms-full.txt`, update
  `docs/llms.txt` when the API changes, and add an entry under `[Unreleased]`
  in `CHANGELOG.md` that says what was broken and why it mattered.
- Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
  `chore:`, `perf:`, `ci:`).

## Releases

Bump `ratelimit_io/version.py`, date the `[Unreleased]` section in
`CHANGELOG.md` and update its link references, merge, then push a `vX.Y.Z` tag.
`.github/workflows/release.yml` verifies the tag against the version, tests,
builds and publishes to PyPI through trusted publishing.
