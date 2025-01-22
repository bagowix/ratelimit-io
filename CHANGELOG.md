# Version history

We follow [Semantic Versions](https://semver.org/).

## WIP

## Version 0.6.5

### Misc

- Updated README with examples for:
  - Using outgoing request handling.

## Version 0.6.4

### Misc

- Updated README with examples for:
  - Using outgoing request handling.
- Updated pre-commit hooks versions

## Version 0.6.3

### Misc

- Updated README with examples for:
  - Using context managers for async workflows.

## Version 0.6.2

### Features

- **Asynchronous Context Manager Support**:
  - Added `__aenter__` and `__aexit__` methods to `RatelimitIO` for use as an asynchronous context manager.
  - Ensures Lua scripts are automatically loaded into Redis when entering the context.
  - Simplifies resource management and integration in async frameworks like FastAPI and aiohttp.

## Version 0.6.1

### Misc

- Update version in pyproject.toml, README.md

## Version 0.6.0

### Features

- Improved Error Handling:
  - Introduced specific exception classes for better error categorization:
    - `RatelimitIOError`: Base class for rate limit-related errors.
    - `RatelimitExceededError`: Raised when the rate limit is exceeded.
    - `ScriptLoadError`: Raised when the Lua script fails to load into Redis.
  - Enhanced error messages for clarity and debugging.
- Logging Support:
  - Added logging for critical operations and errors:
    - Logs errors when the Lua script fails to load into Redis.
    - Logs exception details for debugging unexpected issues.

### Misc

- Code Simplification and Readability:
  - Refactored exception handling for better readability and maintainability.
  - Consolidated duplicated logic between synchronous and asynchronous methods.
- Documentation and Examples:
  - Updated inline comments and docstrings for clarity.
  - Included examples of error handling and logging usage.
- Testing Improvements:
  - Increased test coverage for key generation, rate limit enforcement, and exception handling.
  - Added edge case tests for `LimitSpec` and Redis Lua script loading.

## Version 0.5.0

### Features

- Dynamic `is_incoming` Detection:
  - Added automatic inference for `is_incoming` in decorators based on usage context:
    - Incoming requests (e.g., API handlers): Raise `RatelimitIOError` when limits are exceeded.
    - Outgoing requests (e.g., client-side throttling): Wait until a slot is available.
  - Default behavior is now `is_incoming=True`, suitable for most incoming request use cases.
  - Explicit `is_incoming=False` can still be set during initialization for outgoing request handling.
- Removed `base_url` parameter:
  - Simplified the API by fully replacing `base_url` with `default_key`.
  - Unified logic for key preparation and eliminated redundancy.
- Updated `_prepare_key` logic:
  - Adjusted key priority to: `provided_key > unique_key > default_key > kwargs["ip"] > "unknown_key"`.
  - Added `async/sync` prefixes to keys for better differentiation in mixed environments.
- Enhanced decorator functionality:
  - Supports both synchronous and asynchronous functions.
  - Automatically applies appropriate behavior for incoming or outgoing requests.

### Fixes

- Fixed issues with key generation for mixed environments:
  - Resolved edge cases where default keys were incorrectly prioritized.
  - Ensured robust handling of `kwargs["ip"]` when no `default_key` or `unique_key` is provided.

### Misc

- Updated README and examples:
  - Added detailed explanation for `is_incoming` behavior and dynamic detection.
  - Removed all references to `base_url` and clarified usage of `default_key`.
  - Included examples for both incoming and outgoing request scenarios.
- Improved error messages for missing rate limit specifications (`limit_spec` or `default_limit`).
- Increased test coverage to ensure robust handling of edge cases in key generation, rate limiting, and decorator functionality.

## [Unreleased]

### Misc

- Validation in CI workflow to ensure PyPI builds and publishing only occur for release commits with version tags (e.g., `0.4.0`).

## [Unreleased]

### Misc
- Updated `CONTRIBUTING.md`:
  - Added instructions for setting up `pre-commit` hooks.
  - Clarified that `CHANGELOG.md` must be updated before committing.
  - Removed redundant manual steps for `ruff` and `mypy`, as these are handled by `pre-commit`.

## Version 0.4.0

### Fixes

- Updated `default_key` in `RatelimitIO.__init__` to default to `None` instead of `"unknown_key"`, ensuring `kwargs["ip"]` is used when `unique_key` and `default_key` are not provided.
- Renamed `_prepare_key_and_limit` to `_prepare_key` for clarity.
- Refactored `_prepare_key` to simplify logic and resolve inconsistencies in key generation.
- Fixed key handling in `wait` and `a_wait` to correctly validate and apply rate limits.
- Ensured proper rate-limiting behavior for async and sync decorators with function-specific keys.
- Addressed issues causing `NoneType` errors when `limit_spec` was not provided in `wait` and `a_wait`.

### Misc

- Enhanced key generation with async/sync-specific prefixes to distinguish between function call types.
- Updated `virtualenv` dependency from `20.28.1` to `20.29.0` via `poetry update`.

## Version 0.3.1

### Fixes

- Removed `TypeAlias` import from `typing_extensions` for better compatibility with Python 3.8 and 3.9, as `TypeAlias` is now part of `typing` in Python 3.10+.
- Replaced the `RedisBackend` alias with a direct use of `Union[Redis, AsyncRedis]` in the `backend` parameter of the `__init__` method for backward compatibility.

### Misc

- Updated README with improved examples for:
  - **Using middleware for FastAPI**: Enhanced to include proper error handling with `JSONResponse` for 429 responses, providing more clarity and correctness.
  - **Using middleware for Django**: Added a class-based middleware example leveraging `MiddlewareMixin` for better integration with Django's request/response lifecycle. Also demonstrated an example with DRF's `APIView`.

## Version 0.3.0

### Features

- Introduced a custom error class `RatelimitIOError`, designed to mirror the behavior of `HTTPException`, making it easier to integrate with web frameworks like Flask, Django, and FastAPI.
- Enhanced decorator functionality
  - Automatically applies `base_limit` when the decorator is used without explicit arguments.
- Added seamless support for distinguishing between incoming and outgoing requests using the `is_incoming` flag.
- Implemented 429 Too Many Requests handling:
  - Provides examples for integrating with Flask, Django, and FastAPI to manage error responses gracefully.

### Fixes

- Fixed an issue where `unique_key` fallback to `default_key` was inconsistent.
- Improved Redis script loading to ensure proper error handling and robustness during high-concurrency operations.

### Misc

- Updated README with examples for:
  - Using decorators and context managers for both sync and async workflows.
  - Handling `429 Too Many Requests` errors in popular frameworks.
- Enhanced test coverage to verify all added features and scenarios.

## Version 0.2.5

### Misc

- Adds shields `downloads`

## Version 0.2.4

### Misc

- Edits README.md

## Version 0.2.3

### Features

- Adds additional information in pyproject.toml

## Version 0.2.2

### Misc

- Fix GitHub Action `Build`, delete macos-latest and windows-latest

## Version 0.2.1

### Misc

- Fix GitHub Action `Build`

## Version 0.2.0

### Misc

- Adds wheel builds to GitHub Actions

## Version 0.1.1

### Misc

- Fix `shields` for licence

## Version 0.1.0

- Initial release
