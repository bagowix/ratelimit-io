# Version history

We follow [Semantic Versions](https://semver.org/).

## WIP

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
