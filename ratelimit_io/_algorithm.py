"""The rate limiting algorithms a limiter can enforce."""

from enum import StrEnum

__all__ = ('Algorithm',)


class Algorithm(StrEnum):
    """How a limiter counts requests against a ``Limit``.

    Every algorithm runs as one atomic Lua script on the Redis server, so any
    number of processes sharing a server share the limit.
    """

    FIXED_WINDOW = 'fixed_window'
    """One window per key: it opens with the first request, lasts one period
    and holds ``requests`` slots. Waiting requests fill the windows that
    follow, back to back. Up to twice the limit can pass around the moment one
    window ends and the next begins."""

    SLIDING_WINDOW = 'sliding_window'
    """A log of slot times per key. Exact: at most ``requests`` in any
    period-long interval. Memory grows with the limit (one sorted-set entry per
    slot handed out in the last period, reserved ones included)."""

    GCRA = 'gcra'
    """Generic cell rate algorithm, the token bucket in O(1) memory. Allows a
    burst of ``requests``, then refills one request every
    ``period / requests``."""
