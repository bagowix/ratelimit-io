import pickle

from ratelimit_io import Limit, RateLimitError, RateLimitExceededError


def test__exceeded_error__message__names_limit_and_retry_after() -> None:
    error = RateLimitExceededError(Limit(5, seconds=1), 0.25)

    assert str(error) == 'Rate limit 5/1s exceeded; retry in ~0.250s'


def test__exceeded_error__attributes__expose_limit_and_retry_after() -> None:
    limit = Limit(5, seconds=1)

    error = RateLimitExceededError(limit, 0.25)

    assert error.limit is limit
    assert error.retry_after == 0.25
    assert isinstance(error, RateLimitError)


def test__exceeded_error__pickle__round_trips() -> None:
    error = RateLimitExceededError(Limit(5, seconds=1), 0.25)

    restored = pickle.loads(pickle.dumps(error))  # noqa: S301 - the test's own payload

    assert restored.limit == error.limit
    assert restored.retry_after == error.retry_after
    assert str(restored) == str(error)
