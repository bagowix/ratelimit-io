"""Exception hierarchy for ratelimit-io."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ratelimit_io._limit import Limit

__all__ = ('RateLimitError', 'RateLimitExceededError')


class RateLimitError(Exception):
    """Base class for all errors raised by ratelimit-io."""


class RateLimitExceededError(RateLimitError):
    """Raised when a request is refused because its limit is exhausted.

    The limiter raises it at once, without sleeping, when the next free slot
    is further away than the request may wait.

    Args:
        limit: The limit that refused the request.
        retry_after: Seconds until a request on the same key can be allowed.
            An HTTP ``Retry-After`` header takes whole seconds, so round it up.
    """

    def __init__(self, limit: 'Limit', retry_after: float) -> None:
        # Both go to Exception.__init__ so the error survives pickling, e.g. on
        # its way back from a worker process.
        super().__init__(limit, retry_after)
        self.limit = limit
        self.retry_after = retry_after

    def __str__(self) -> str:
        return f'Rate limit {self.limit} exceeded; retry in ~{self.retry_after:.3f}s'
