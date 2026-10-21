import pytest

from ratelimit_io import Key


def test__key__template_not_a_string__raises_type_error() -> None:
    with pytest.raises(TypeError, match='template must be a str, got int'):
        Key(42)  # type: ignore[arg-type]


def test__key__empty_template__raises() -> None:
    with pytest.raises(ValueError, match='template must not be empty'):
        Key('')


@pytest.mark.parametrize(
    'template', ['user:{user_id', 'user:}', '{user_id!z}', '{user_id:{width}}', '{user_id:{}}']
)
def test__key__malformed_template__raises(template: str) -> None:
    with pytest.raises(ValueError, match='invalid key template'):
        Key(template)


@pytest.mark.parametrize('template', ['user:{}', 'user:{0}', '{0.name}'])
def test__key__positional_field__raises(template: str) -> None:
    with pytest.raises(ValueError, match='has a positional field'):
        Key(template)
