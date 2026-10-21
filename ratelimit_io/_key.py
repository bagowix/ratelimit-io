"""``Key``: a decorator key filled from the arguments of each call."""

import inspect
import string
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

__all__ = ('Key', 'check_plain_key', 'template_key')

_CONVERSIONS = frozenset({None, 'r', 's', 'a'})


@dataclass(frozen=True, slots=True)
class Key:
    """A bucket key that ``str.format`` fills from the arguments of each call.

    ``@limiter(key=Key('user:{user_id}'))`` gives every user a bucket of their
    own. A field starts with the name of a parameter of the decorated function
    and may go on to attributes and items, as ``{request.client.host}`` or
    ``{headers[x-api-key]}``. A plain ``str`` key is never formatted.

    Args:
        template: The ``str.format`` template of the key.

    Raises:
        TypeError: If ``template`` is not a str.
        ValueError: If ``template`` is empty or malformed, has a positional
            field such as ``{}`` or ``{0}``, an unknown conversion, or a field
            inside a format spec.
    """

    template: str

    def __post_init__(self) -> None:
        if not isinstance(self.template, str):  # pyright: ignore[reportUnnecessaryIsInstance] - checks untyped callers
            raise TypeError(f'template must be a str, got {type(self.template).__name__}')

        if not self.template:
            raise ValueError('template must not be empty')

        try:
            roots = _field_roots(self.template)
        except ValueError as error:
            raise ValueError(f'invalid key template {self.template!r}: {error}') from None

        if any(not root or root.isdecimal() for root in roots):
            raise ValueError(
                f'{self.template!r} has a positional field; '
                'name a parameter instead, as in {user_id}'
            )


def template_key(
    key: Key, signature: inspect.Signature, name: str
) -> Callable[[Mapping[str, object]], str]:
    """Return the function that fills ``key`` from the bound arguments of a call of ``name``."""
    for root in _field_roots(key.template):
        if root not in signature.parameters:
            raise TypeError(f'{name} has no parameter {root!r} for its key {key.template!r}')

    formatter = _KeyFormatter(name)

    return lambda arguments: formatter.vformat(key.template, (), arguments)


def check_plain_key(key: str, name: str) -> None:
    """Refuse a plain decorator key of ``name`` that reads as a ``Key`` template."""
    # Unbalanced braces make no template, so such a key stays the literal it is.
    try:
        roots = _field_roots(key)
    except ValueError:
        return

    if roots:
        literal = key.replace('{', '{{').replace('}', '}}')

        raise ValueError(
            f'the key {key!r} of {name} is a plain string and would be one bucket for '
            f'every call; pass Key({key!r}) to fill it from the arguments, '
            f'or Key({literal!r}) to keep the braces'
        )


class _KeyFormatter(string.Formatter):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def get_field(
        self, field_name: str, args: Sequence[object], kwargs: Mapping[str, object]
    ) -> tuple[object, str]:
        value, root = super().get_field(field_name, args, kwargs)

        # 'user:None' or 'user:' would count every call without a user in one bucket.
        if value is None or (isinstance(value, str) and not value):
            raise ValueError(
                f'the key of {self._name}: {{{field_name}}} is {value!r}, '
                'and every such call would share one bucket'
            )

        return value, root


def _field_roots(template: str) -> tuple[str, ...]:
    """Return the parameter name each field of ``template`` starts with.

    Raises ``ValueError`` for a malformed template, an unknown conversion, and a
    field inside a format spec, which would escape the check of its name.
    """
    roots: list[str] = []

    for _, field, spec, conversion in string.Formatter().parse(template):
        if field is None:
            continue

        if conversion not in _CONVERSIONS:
            raise ValueError(f'unknown conversion !{conversion} in {{{field}}}')

        if spec and '{' in spec:
            raise ValueError(f'the format spec of {{{field}}} holds a field')

        roots.append(field.partition('.')[0].partition('[')[0])

    return tuple(roots)
