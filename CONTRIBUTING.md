# Contributing to RatelimitIO

We welcome contributions to `ratelimit-io`! Whether you’re fixing bugs, improving documentation, or adding features, your help is appreciated.

---

## Getting Started

### Installing Dependencies

We use [Poetry](https://github.com/python-poetry/poetry) to manage dependencies. First, install Poetry if you haven’t already:

```bash
pip install poetry
```

Then, install the project dependencies:

```bash
poetry install
```

To activate the virtual environment, run:

```bash
poetry shell
```

## Setting Up Pre-Commit Hooks

We use [pre-commit](https://pre-commit.com/) to automate code quality checks. Before committing any changes, ensure you install the pre-commit hooks:

```bash
pre-commit install
```

These hooks will automatically run `ruff`, `mypy`, and other checks on every commit.

## Development Workflow

### Running Tests

We use `pytest` for testing. To run all tests:

```bash
pytest
```

### Pre-Commit Hooks

After setting up `pre-commit`, the following checks will run automatically when you commit your changes:

- Code linting (`ruff`)
- Type checking (`mypy`)
- Formatting and other static checks

You can manually trigger all pre-commit hooks to verify your code before committing:

```bash
pre-commit run --all-files
```

### Updating `CHANGELOG.md`

Before committing, ensure that you update the `CHANGELOG.md` file to include a brief summary of your changes:

- Use appropriate categories (e.g., `Fixes`, `Features`, `Misc`).
- Write concise, clear descriptions of your changes.

## Submitting Your Code

We follow a simple branch-based workflow:

1. **Create a Branch**: Create a branch named `issue-<number>` or `feature-<description>` for your changes:

```bash
git checkout -b issue-123
```

2. **Make Changes**: Write your code, ensuring that:
   * All tests pass (`pytest`).
   * Type checks succeed (`mypy`).
   * The code is linted (`ruff`).

3. **Update Documentation**: Update the README.md and any relevant docstrings for new features or changes.

4. **Update** `CHANGELOG.md`: Add a summary of your changes.

5. **Push Changes**: Push your branch to the repository:

```bash
git push origin issue-123
```

6. **Create a Pull Request**: Open a pull request to the master branch. Make sure your PR includes:
   * A clear description of your changes.
   * Links to any relevant issues.

---

## Before Submitting

Ensure the following tasks are completed:

1. All tests pass:

```bash
pytest
```

2. Pre-commit hooks pass:

```bash
pre-commit run --all-files
```

3. The `CHANGELOG.md` file is updated with relevant changes.

4. Add or update tests to cover new functionality.

5. Document any significant changes.

---

## Other Ways to Help

* Spread the word about `ratelimit-io`.
* Share use cases or examples of how you’re using the library.
