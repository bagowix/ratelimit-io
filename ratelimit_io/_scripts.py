"""Lua sources of the rate limiting algorithms.

Every script takes ``KEYS[1]`` (the bucket), ``ARGV[1]`` (requests per period),
``ARGV[2]`` (the period in milliseconds), ``ARGV[3]`` (how many milliseconds
the request may wait, ``inf`` for no limit) and ``ARGV[4]`` (a member unique
to the request, used by the sliding window).

A script reserves the earliest free slot and returns how many milliseconds
remain until it, ``0`` meaning now. A slot further away than the request may
wait is not reserved: the script records nothing and returns the negated wait,
always ``-1`` or less. Reserving instead of retrying gives one round trip per
request and serves waiters first come, first served across processes.

Time is the server's ``TIME`` in whole microseconds: one clock for every
client, and exact arithmetic. Expiry only collects buckets
nobody uses; every decision reads the stored times, so a key that lost its
expiry still counts correctly.
"""

from typing import Final

from ratelimit_io._algorithm import Algorithm

__all__ = ('SCRIPTS',)

_PRELUDE: Final = """
local limit = tonumber(ARGV[1])
local period = tonumber(ARGV[2]) * 1000
local budget = tonumber(ARGV[3]) * 1000
local time = redis.call('TIME')
local now = time[1] * 1000000 + time[2]
"""

# Windows follow each other back to back while requests wait for them, so the
# key holds only the last one: its start and how many slots it has handed out.
_FIXED_WINDOW: Final = (
    _PRELUDE
    + """
local window = redis.call('HMGET', KEYS[1], 'start', 'count')
local start = tonumber(window[1])
local count = tonumber(window[2])
if not start or now >= start + period then
    start = now
    count = 0
elseif count >= limit then
    start = start + period
    count = 0
end
local wait = math.max(start - now, 0)
if wait > budget then
    return -math.ceil(wait / 1000)
end
redis.call('HSET', KEYS[1], 'start', start, 'count', count + 1)
redis.call('PEXPIRE', KEYS[1], math.ceil((start + period - now) / 1000))
return math.ceil(wait / 1000)
"""
)

# The key logs the time of every slot handed out, reserved ones included. A
# new slot opens one period after the slot ``limit`` places before it.
_SLIDING_WINDOW: Final = (
    _PRELUDE
    + """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - period)
local count = redis.call('ZCARD', KEYS[1])
local at = now
if count >= limit then
    local blocker = redis.call('ZRANGE', KEYS[1], count - limit, count - limit, 'WITHSCORES')
    at = math.max(tonumber(blocker[2]) + period, now)
end
local wait = at - now
if wait > budget then
    return -math.ceil(wait / 1000)
end
redis.call('ZADD', KEYS[1], at, ARGV[4])
redis.call('PEXPIRE', KEYS[1], math.ceil((at + period - now) / 1000))
return math.ceil(wait / 1000)
"""
)

# The theoretical arrival time (TAT) is when the bucket would be empty again; a
# slot opens once the TAT, advanced by one emission interval, is at most one
# period ahead. The key stores the TAT as a backlog relative to the moment it
# was written, counted in 1/limit microseconds: a request adds one whole
# period and a microsecond drains `limit`, so the numbers stay whole while
# period * limit stays under 2^53 microseconds. A fractional interval would let
# `limit` of them add up to a hair over the period and refuse the last request
# of a burst; an absolute TAT near 2^51 microseconds would lose up to a quarter
# of a microsecond on every addition.
_GCRA: Final = (
    _PRELUDE
    + """
local state = redis.call('HMGET', KEYS[1], 'written', 'backlog')
local written = tonumber(state[1]) or now
local backlog = math.max((tonumber(state[2]) or 0) - (now - written) * limit, 0) + period
local wait = math.max(backlog - period * limit, 0)
if wait > budget * limit then
    return -math.ceil(wait / limit / 1000)
end
redis.call('HSET', KEYS[1], 'written', now, 'backlog', backlog)
redis.call('PEXPIRE', KEYS[1], math.ceil(backlog / limit / 1000))
return math.ceil(wait / limit / 1000)
"""
)

SCRIPTS: Final[dict[Algorithm, str]] = {
    Algorithm.FIXED_WINDOW: _FIXED_WINDOW,
    Algorithm.SLIDING_WINDOW: _SLIDING_WINDOW,
    Algorithm.GCRA: _GCRA,
}
