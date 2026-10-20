"""Generate ``docs/llms-full.txt`` by inlining every documentation page.

``llms.txt`` is the short index (links only); ``llms-full.txt`` is the same
content expanded inline so an agent can ingest the whole manual in one request.
Regenerate after editing any page::

    uv run python scripts/build_llms_full.py

The page order mirrors the ``## Docs`` section of ``docs/llms.txt`` so the two
files never disagree on structure.
"""

from pathlib import Path

_DOCS = Path(__file__).resolve().parent.parent / 'docs'

# Same order as the index in docs/llms.txt.
_PAGES = (
    'getting-started.md',
    'guides/algorithms.md',
    'guides/keys.md',
    'guides/waiting.md',
    'frameworks.md',
    'migration.md',
    'reference.md',
)

_HEADER = """# ratelimit-io — full documentation

> Distributed rate limiting for Python on Redis: fixed window, sliding window
> and GCRA as atomic Lua scripts, one RateLimiter class for async and sync code,
> for incoming requests a server sheds and outgoing requests a client waits for.

This file inlines every documentation page in reading order. It is generated
from the Markdown sources by ``scripts/build_llms_full.py``; edit the pages in
``docs/``, not this file.
"""


def build() -> str:
    """Return the full inlined documentation as a single string."""
    parts = [_HEADER]
    for page in _PAGES:
        body = (_DOCS / page).read_text(encoding='utf-8').strip()
        parts.append(f'\n\n---\n\n<!-- source: docs/{page} -->\n\n{body}')

    return ''.join(parts) + '\n'


def main() -> None:
    """Write the assembled documentation to ``docs/llms-full.txt``."""
    (_DOCS / 'llms-full.txt').write_text(build(), encoding='utf-8')


if __name__ == '__main__':
    main()
