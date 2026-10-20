import dataclasses
import math

import pytest

from ratelimit_io import Limit


def test__limit__period_parts__add_up() -> None:
    limit = Limit(10, seconds=30, minutes=2, hours=1)

    assert limit.total_seconds() == 3750
    assert limit.period_ms() == 3_750_000


@pytest.mark.parametrize(('seconds', 'period_ms'), [(0.25, 250), (1.001, 1001)])
def test__limit__fractional_seconds__keep_millisecond_precision(
    seconds: float, period_ms: int
) -> None:
    limit = Limit(1, seconds=seconds)

    assert limit.period_ms() == period_ms


@pytest.mark.parametrize(
    ('limit', 'expected'),
    [
        (Limit(5, seconds=1), '5/1s'),
        (Limit(100, hours=1), '100/3600s'),
        (Limit(3, seconds=0.5), '3/0.5s'),
        (Limit(1, seconds=1234567), '1/1234567s'),
        (Limit(1, seconds=0.0015), '1/0.002s'),
    ],
)
def test__limit__str__shows_requests_per_period(limit: Limit, expected: str) -> None:
    assert str(limit) == expected


def test__limit__same_requests_per_period__are_equal_and_hash_alike() -> None:
    by_seconds = Limit(5, seconds=60)
    by_minutes = Limit(5, minutes=1)

    assert by_seconds == by_minutes
    assert hash(by_seconds) == hash(by_minutes)


@pytest.mark.parametrize('other', [Limit(6, minutes=1), Limit(5, minutes=2), '5/60s'])
def test__limit__other_requests_period_or_type__are_not_equal(other: object) -> None:
    assert Limit(5, minutes=1) != other


@pytest.mark.parametrize('requests', [0, -1])
def test__limit__requests_not_a_positive_integer__raises(requests: int) -> None:
    with pytest.raises(ValueError, match='requests must be a positive integer'):
        Limit(requests, seconds=1)


def test__limit__integer_like_requests__are_stored_as_an_int() -> None:
    class Count:
        def __index__(self) -> int:
            return 5

    limit = Limit(Count(), seconds=1)  # type: ignore[arg-type]

    assert type(limit.requests) is int
    assert limit == Limit(5, seconds=1)


@pytest.mark.parametrize(
    ('options', 'message'),
    [
        ({'requests': 2.5, 'seconds': 1}, 'requests must be an integer, got float'),
        ({'requests': '5', 'seconds': 1}, 'requests must be an integer, got str'),
        ({'requests': True, 'seconds': 1}, 'requests must be an integer, got bool'),
        ({'requests': 5, 'seconds': '1'}, 'seconds must be a number, got str'),
        ({'requests': 5, 'minutes': True}, 'minutes must be a number, got bool'),
        ({'requests': 5, 'hours': None}, 'hours must be a number, got NoneType'),
    ],
)
def test__limit__argument_of_the_wrong_type__raises_type_error(
    options: dict[str, object], message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        Limit(**options)  # type: ignore[arg-type]


@pytest.mark.parametrize('value', [-1, math.nan, math.inf])
@pytest.mark.parametrize('part', ['seconds', 'minutes', 'hours'])
def test__limit__period_part_negative_or_not_finite__raises(part: str, value: float) -> None:
    with pytest.raises(ValueError, match=f'{part} must be a finite number >= 0'):
        Limit(1, **{part: value})


@pytest.mark.parametrize('seconds', [0, 0.0004])
def test__limit__period_under_a_millisecond__raises(seconds: float) -> None:
    with pytest.raises(ValueError, match='at least 1 millisecond'):
        Limit(1, seconds=seconds)


def test__limit__period_parts__are_keyword_only() -> None:
    with pytest.raises(TypeError):
        Limit(1, 1)  # type: ignore[misc]


def test__limit__assignment__raises() -> None:
    limit = Limit(1, seconds=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        limit.requests = 2  # type: ignore[misc]
