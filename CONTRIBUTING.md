# Contributing to ratelimit-io

Thanks for your interest in improving ratelimit-io. This guide covers the local
setup, the checks your change must pass, and how a release is cut.

## Development setup

ratelimit-io uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management. With uv installed:

```bash
git clone https://github.com/bagowix/ratelimit-io
cd ratelimit-io
uv sync               # creates the venv and installs the dev dependencies
uv run prek install   # one-time: installs the git hooks
```

## Running the checks

CI runs exactly these on Python 3.11 to 3.15. Run them locally before opening a
pull request:

```bash
uv run ruff format --check     # formatting
uv run ruff check              # linting
uv run mypy                    # type checking (strict)
uv run pyright                 # type checking (strict, second checker)
uv run pyrefly check           # type checking (strict, third opinion)
uv run pytest --cov            # tests, 100% coverage required
uv run zizmor .github/         # GitHub Actions and Dependabot audit
uv run zensical build --strict # docs, including broken links
```

A single test: `uv run pytest tests/test_limiter.py::test__acquire_sync__over_limit__raises_with_retry_after`.
The suite runs in parallel through pytest-xdist; add `-n 0` to run it serially,
for example under `--pdb`.

### Redis

`uv run pytest` needs no server: the tests run against in-process
[fakeredis](https://github.com/cunla/fakeredis-py), which executes the Lua
scripts too. The concurrency tests prove atomicity, which only a real server can
show, so they are skipped there. Point the suite at a real Redis or Valkey to
run everything:

```bash
docker run --rm -p 6379:6379 redis:7          # or valkey/valkey:8
RATELIMIT_IO_TEST_REDIS_URL=redis://localhost:6379/0 uv run pytest
```

The tests never flush the server. Each test works under its own key prefix and
deletes its keys afterwards, so a shared development Redis is safe.

CI runs the suite against Redis 7 on every Python version, against Redis 5,
Redis 6.2 and Valkey 8, against fakeredis, and against the oldest supported
redis-py (`deps-min` job). Redis 5 needs `?protocol=2` in the URL, because
redis-py 8 speaks RESP3 by default.

`tests/test_scripts.py` runs the Lua scripts on a clock each test sets, to pin
their arithmetic to the microsecond. Extend it when a script changes.

### Workflows

Every action in `.github/workflows/` is pinned to a commit SHA with the version
in a trailing comment. To add one, write the tag and let zizmor rewrite it:
`GH_TOKEN=$(gh auth token) uv run zizmor --fix=all .github/`. Routine bumps
come from Dependabot.

### Public API compatibility

`.github/workflows/api-compatibility.yml` runs
[`griffe check`](https://mkdocstrings.github.io/griffe/) on every pull request
and diffs the public API against the latest release tag. Run it locally with
`uv run griffe check ratelimit_io --search .`. A breaking change must be
deliberate: label the pull request `breaking-change` and record it in
`CHANGELOG.md`.

## Expectations

- **Tests first.** New behaviour and bug fixes come with tests, and the suite
  keeps 100% branch coverage. Test names follow
  `test__unit__state__expected`.
- **Types are part of the API.** The public surface stays fully typed;
  `tests/typing_surface.py` pins what users' type checkers infer.
- **One dependency.** The package depends on redis-py and nothing else. Its
  floor in `pyproject.toml` is a compatibility statement: raising it on purpose
  means raising the pin in the `deps-min` CI job too.
- **Conventional commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
  `chore:`, `perf:`, `ci:`. A `commit-msg` hook enforces them.
- **Docs and changelog.** A user-facing change updates the relevant page under
  `docs/`, regenerates `docs/llms-full.txt` with
  `uv run python scripts/build_llms_full.py`, and adds an entry under
  `[Unreleased]` in `CHANGELOG.md`.

## Releasing

1. Bump `VERSION` in `ratelimit_io/version.py`.
2. In `CHANGELOG.md`, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, open a
   new empty `[Unreleased]` above it, and update the link references at the
   bottom.
3. Merge to `main`, then tag the merge commit and push the tag:
   `git tag vX.Y.Z && git push origin vX.Y.Z`.

`.github/workflows/release.yml` checks that the tag matches `VERSION`, runs the
tests, builds the sdist and wheel, publishes them to PyPI through trusted
publishing and opens a GitHub release.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating you agree to uphold it.
