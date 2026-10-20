# Waiting for a slot

`max_wait` is how many seconds a request may wait for a slot. It is set on the
limiter and can be overridden per call or per decorated function.

```python
limiter = RateLimiter(client, limit=Limit(10, seconds=1), max_wait=5)

await limiter.acquire('reports')  # waits up to 5 s
await limiter.acquire('reports', max_wait=0)  # fails at once


@limiter(max_wait=30)
async def nightly_export() -> None: ...
```

## Fail at once: incoming requests

`max_wait=0` is the default. A server that is over its limit should answer
`429 Too Many Requests` immediately: holding the connection open only ties up a
worker, and the client knows best whether to retry. The error's `retry_after`,
rounded up, goes into the `Retry-After` header.

## Wait: outgoing requests

A client of someone else's API usually has to make the call anyway. With a
budget, a request that finds the bucket full reserves the next free slot and
sleeps until it comes.

The script that counts the request makes the reservation in the same round
trip. The limiter then sleeps once and returns; it never polls Redis and never
retries. A hundred waiting workers cost a hundred sleeping coroutines and one
round trip each, and each one wakes at the slot it booked and goes ahead
without asking Redis again. GCRA spaces those slots evenly. The window
algorithms hand them out the way they admit requests, so waiters booked for the
same moment, such as the start of the next fixed window, wake together.

Waiting requests are served in arrival order, across every process that
shares the bucket. A request that arrives while others wait queues behind
them, even with `max_wait=0`, so its `retry_after` counts the queue too.

When the next free slot lies further away than the budget, the limiter
reserves nothing and raises `RateLimitExceededError` at once. With
`Limit(1, minutes=1)` and `max_wait=5`, a refused request fails straight away
with `retry_after` close to 60, without wasting five seconds first.

## Waiting without a deadline

`max_wait=math.inf` waits as long as it takes. Use it for background jobs that
must eventually run, never on a request path.

## Cancellation

`acquire()` sleeps with `asyncio.sleep`, so it is cancelled like any other
coroutine: wrap it in `asyncio.timeout()` or cancel its task. A request
cancelled while it sleeps has already reserved its slot, and that slot goes
unused. The limit still holds, but the requests queued behind it wait as if it
had run. To bound the wait, pass `max_wait`: a request that would wait too long
then fails before it reserves anything.

## Connections and retries

Every `acquire()` is one round trip and holds a connection for that trip only,
never while it sleeps. Still, N calls in flight at once need N connections. A
redis-py connection pool has a `max_connections` cap (100 by default in
redis-py 8) and raises `MaxConnectionsError` when a call needs one more. For
bigger bursts, raise the cap or pass a `BlockingConnectionPool`, which makes
callers wait for a free connection instead and raises `ConnectionError` once
its `timeout`, 20 seconds by default, runs out.

The limiter adds no retries or fallbacks of its own. When Redis is down,
`acquire()` raises redis-py's error once the client's timeouts and `retry`
settings give up. When redis-py retries a command whose reply was lost, the
script runs a second time for a request it has already counted. The fixed
window and GCRA then count the request twice. The sliding window counts it
once, at the slot the second run picks, which can be a whole period later. The
second run may also refuse a request the first one let through. A lost reply
can waste slots, and the limit holds all the same.
