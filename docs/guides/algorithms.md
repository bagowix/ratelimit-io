# Algorithms

A limiter counts requests with one of three algorithms. Each one is a single
Lua script that Redis runs atomically, so any number of processes can race for
the same bucket and exactly the allowed number of requests get through.

```python
from ratelimit_io import Algorithm, Limit, RateLimiter

limiter = RateLimiter(client, limit=Limit(100, minutes=1), algorithm=Algorithm.SLIDING_WINDOW)
```

`Algorithm.FIXED_WINDOW` is the default. To read the choice from configuration,
convert the string: `Algorithm(settings.rate_limit_algorithm)` accepts
`'fixed_window'`, `'sliding_window'` and `'gcra'`.

## At a glance

| | Fixed window | Sliding window | GCRA |
|---|---|---|---|
| Guarantee | at most N per window, up to 2N around a window boundary | at most N in any period-long interval | a burst of at most N, then N per period on average |
| Memory per bucket | two numbers | one entry per slot handed out in the last period | two numbers |
| `retry_after` on refusal | until the window ends | until the oldest request leaves the window | until the next request conforms |
| Pick it for | per-user or per-IP limits | strict quotas of someone else's API | smooth traffic, token-bucket semantics |

These rules hold for every algorithm:

- **A refused request is not recorded.** A client that keeps knocking while
  blocked does not push its own unblocking further away.
- **A waiting request reserves its slot.** With a wait budget, a request that
  finds the bucket full takes the next free slot in advance and sleeps until
  it. Waiters are served in arrival order; see
  [Waiting for a slot](waiting.md).
- **Time comes from Redis.** Every script reads the server's `TIME`, to the
  microsecond. Clock skew between application hosts cannot bend a limit, and
  a bucket that loses its expiry still counts correctly, because expiry only
  removes buckets nobody uses.

## Fixed window

The first request opens a window one period long with N slots. Requests take
the slots of the current window; once they are gone, a request is refused
until the window ends, or with a wait budget reserves a slot in the next
window, which starts the moment the current one ends.

It is the simplest algorithm, and its weakness is the boundary: N requests at
the end of one window and N more at the start of the next pass within a very
short time. When that burst is harmless, which it is for most per-user limits,
the fixed window is the right default.

## Sliding window

A log of the slots handed out per bucket, kept in a sorted set. A request is
allowed when fewer than N slots fall within the last period, so no period-long
interval ever holds more than N. A waiting request is logged at the slot it
reserves, one period after the slot N places before it.

The price is memory: a bucket holds one entry per slot handed out in the last
period, plus one per waiting request. For 100 requests a minute that is
nothing. For a million requests a day per key, choose GCRA.

Pick the sliding window when exceeding the limit has a cost you cannot absorb,
typically an external API that bans clients for going over its quota. Set the
limit a little below that quota all the same: the limiter counts a request when
it takes its slot, and the network delays each request by a different amount
on its way to the provider.

## GCRA

The generic cell rate algorithm is a token bucket in constant memory: per
bucket it keeps how far ahead the theoretical arrival time of the next request
lies. A full bucket allows a burst of N requests; after that it refills one
request every `period / N`.

GCRA limits the rate, not the count per window. Over a long run the average is
exactly N per period, and traffic comes out evenly spread. Within one period-long
interval, though, a full burst plus a period of refills can add up to
2N − 1 requests.

`retry_after` is exact and usually short: after a burst against
`Limit(60, minutes=1)` the next request conforms one second later.

## Switching algorithms

The algorithm is part of the bucket name, so a limiter with a different
algorithm starts with empty buckets instead of misreading the old ones. Switching
in a deploy resets every counter once.
