"""Immutable rate limit with eager validation."""

import math
import numbers
import operator
from dataclasses import KW_ONLY, dataclass

__all__ = ('Limit',)


@dataclass(frozen=True, slots=True)
class Limit:
    """Allow ``requests`` requests per period of ``seconds + minutes + hours``.

    The period may be fractional (``seconds=0.5``) but is enforced with
    millisecond precision, so it must be at least one millisecond long. Limits
    that allow the same requests per the same period are equal however the
    period is spelled: ``Limit(1, minutes=1) == Limit(1, seconds=60)``.

    Args:
        requests: Maximum number of requests per period.
        seconds: Seconds added to the period.
        minutes: Minutes added to the period.
        hours: Hours added to the period.

    Raises:
        TypeError: If ``requests`` is not an integer or a period part is not a
            number; a bool is neither.
        ValueError: If ``requests`` is not positive, a period part is negative
            or not finite, or the period is shorter than a millisecond.
    """

    requests: int
    _: KW_ONLY
    seconds: float = 0
    minutes: float = 0
    hours: float = 0

    def __post_init__(self) -> None:
        # bool is an int, and requests=True reads like a switch, not one request.
        if isinstance(self.requests, bool):
            raise TypeError('requests must be an integer, got bool')

        # operator.index refuses floats such as 2.5, which Lua would compare as
        # they are and quietly allow a third request.
        try:
            requests = operator.index(self.requests)
        except TypeError:
            raise TypeError(
                f'requests must be an integer, got {type(self.requests).__name__}'
            ) from None

        if requests <= 0:
            raise ValueError(f'requests must be a positive integer, got {requests}')

        # An integer type of another library, such as numpy.int64, becomes an
        # int that redis-py can send and that compares like one.
        object.__setattr__(self, 'requests', requests)

        parts: tuple[tuple[str, object], ...] = (
            ('seconds', self.seconds),
            ('minutes', self.minutes),
            ('hours', self.hours),
        )
        for name, value in parts:
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise TypeError(f'{name} must be a number, got {type(value).__name__}')

            number = float(value)
            if not (math.isfinite(number) and number >= 0):
                raise ValueError(f'{name} must be a finite number >= 0, got {value!r}')

        if self.period_ms() < 1:
            raise ValueError(
                f'the period must be at least 1 millisecond, got {self.total_seconds()!r}s'
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Limit):
            return NotImplemented

        return (self.requests, self.period_ms()) == (other.requests, other.period_ms())

    def __hash__(self) -> int:
        return hash((self.requests, self.period_ms()))

    def __str__(self) -> str:
        # The period as Redis enforces it, so equal limits print alike.
        return f'{self.requests}/{self.period_ms() / 1000:.12g}s'

    def total_seconds(self) -> float:
        """Return the period length in seconds."""
        return self.seconds + self.minutes * 60 + self.hours * 3600

    def period_ms(self) -> int:
        """Return the period length in whole milliseconds, as Redis enforces it."""
        return round(self.total_seconds() * 1000)
