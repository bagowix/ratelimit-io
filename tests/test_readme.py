"""Keeps the README usable away from GitHub.

The README is also the PyPI long description, and PyPI resolves a relative link
against ``pypi.org`` rather than the repository: every relative link a reader
clicks there is a 404. Absolute urls are the fix; these tests keep them
absolute and keep each documentation url pointing at a page that exists.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / 'README.md').read_text(encoding='utf-8')

_DOCS_SITE = 'https://bagowix.github.io/ratelimit-io/'
_LINK = re.compile(r'\]\((?P<target>[^)\s]+)\)|<(?P<bare>https://[^>\s]+)>')


def _targets() -> tuple[str, ...]:
    return tuple(match['target'] or match['bare'] for match in _LINK.finditer(_README))


def _docs_page(url: str) -> Path:
    page = url.removeprefix(_DOCS_SITE).split('#')[0].strip('/')
    if not page:
        return _ROOT / 'docs' / 'index.md'

    # A file such as llms.txt is published as it is; a page is built from Markdown.
    return _ROOT / 'docs' / (page if '.' in Path(page).name else f'{page}.md')


def test__readme_links__every_target__is_absolute_or_an_anchor() -> None:
    relative = [target for target in _targets() if not target.startswith(('https://', '#'))]

    assert relative == [], f'relative links 404 on PyPI: {relative}'


def test__readme_links__every_documentation_url__matches_a_docs_page() -> None:
    missing = [
        url for url in _targets() if url.startswith(_DOCS_SITE) and not _docs_page(url).exists()
    ]

    assert missing == [], f'documentation urls with no page behind them: {missing}'
