from typing import Optional
from typing import Union

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from typing_extensions import TypeAlias

from ratelimit_io.rate_limit import RatelimitIO  # noqa


class RatelimitIOError(Exception):
    """Raised when the rate limit is exceeded."""


class LimitSpec:
    """
    Specifies the number of requests allowed in a time frame.

    Attributes:
        requests (int): Maximum number of requests.
        seconds (Optional[int]): Time frame in seconds.
        minutes (Optional[int]): Time frame in minutes.
        hours (Optional[int]): Time frame in hours.
    """

    def __init__(
        self,
        requests: int,
        seconds: Optional[int] = None,
        minutes: Optional[int] = None,
        hours: Optional[int] = None,
    ):
        if requests <= 0:
            raise ValueError("Requests must be greater than 0.")

        self.requests = requests
        self.seconds = seconds
        self.minutes = minutes
        self.hours = hours

        if self.total_seconds() == 0:
            raise ValueError(
                "At least one time frame "
                "(seconds, minutes, or hours) must be provided."
            )

    def total_seconds(self) -> int:
        """
        Calculates the total time frame in seconds.

        Returns:
            int: Total time in seconds.
        """
        total = 0
        if self.seconds:
            total += self.seconds
        if self.minutes:
            total += self.minutes * 60
        if self.hours:
            total += self.hours * 3600
        return total

    def __str__(self) -> str:
        return f"{self.requests}/{self.total_seconds()}s"


RedisBackend: TypeAlias = Union[Redis, AsyncRedis]
