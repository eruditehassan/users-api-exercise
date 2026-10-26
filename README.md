# Users Integration API

A REST API that retrieves every user from the [DummyJSON Users API](https://dummyjson.com/docs/users), keeps five fields for each user and lets consumers filter by first and last name. Every response containing user data has the same structure, and the service fails clearly, rather than returning incomplete data, when the upstream API misbehaves.

Built with Python, FastAPI, httpx and Pydantic, and tested with pytest.

## Requirements

- Python 3.14 (developed and tested with 3.14.7).
- Network access to `dummyjson.com` to run the service. The automated tests run offline.

## Running the service

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

`requirements-dev.txt` installs the runtime requirements plus the test tools; `requirements.txt` alone is enough to run the service.

The API is then available at `http://127.0.0.1:8000`. Interactive documentation, where each request below can be tried from the browser, is at `http://127.0.0.1:8000/docs`.

## Example requests

```bash
curl "http://127.0.0.1:8000/users"
curl "http://127.0.0.1:8000/users?firstName=Emily"
curl "http://127.0.0.1:8000/users?lastName=Smith"
curl "http://127.0.0.1:8000/users?firstName=Emily&lastName=Smith"
```

Response to `GET /users?firstName=Emily&lastName=Johnson` (DummyJSON data on 26 October 2026):

```json
{
  "total": 208,
  "count": 1,
  "users": [
    {
      "id": 1,
      "firstName": "Emily",
      "lastName": "Johnson",
      "email": "emily.johnson@x.dummyjson.com",
      "phone": "+81 965-431-3024"
    }
  ]
}
```

## Running the tests

```bash
pytest
```

This runs the offline suite. DummyJSON is replaced by an in-memory fake, so the results do not depend on the network or on the live data.

```bash
pytest -m live
```

This runs two contract tests against the real DummyJSON API, to confirm it still behaves as the offline tests assume. They are excluded from the default run.

## Configuration

Settings are read from environment variables when the service starts.

| Variable | Default | Purpose |
|---|---|---|
| `UPSTREAM_BASE_URL` | `https://dummyjson.com` | Base URL of the users API |
| `UPSTREAM_TIMEOUT_SECONDS` | `5` | httpx timeout for each connect, read, write and connection-pool wait |
| `UPSTREAM_PAGE_SIZE` | `100` | Users requested per upstream page |

## API

### `GET /users`

| Query parameter | Description |
|---|---|
| `firstName` | Optional. Exact first name to match, case-insensitive. |
| `lastName` | Optional. Exact last name to match, case-insensitive. |

When both are supplied, a user must match both. Without filters, every user is returned.

A successful response (`200 OK`) has these fields:

| Field | Meaning |
|---|---|
| `total` | Users reported by DummyJSON, before filtering |
| `count` | Users included in this response, after filtering |
| `users` | The matching users in upstream order, each with `id`, `firstName`, `lastName`, `email` and `phone` |

No match is still a `200 OK`, with `count` 0 and an empty `users` list.

Errors return `{"detail": "<reason>"}` and never contain user data:

| Status | When | `detail` |
|---|---|---|
| `504 Gateway Timeout` | The upstream timed out on any page | Upstream user service timed out |
| `502 Bad Gateway` | The upstream returned an error status | Upstream user service returned HTTP 503 |
| `502 Bad Gateway` | The upstream could not be reached | Could not reach upstream user service |
| `502 Bad Gateway` | The body was not JSON, had the wrong shape, or a user record had a missing or wrongly typed field | Upstream user service returned an unexpected response |
| `502 Bad Gateway` | The pages were inconsistent: an empty page before all users arrived, a repeated user id, more users than `total`, or `total` changing between pages | Upstream user service returned an unexpected response: empty page before all users were received |

## Approach and decisions

**Retrieving every user.**
- The service requests pages with `limit` and `skip`, starting each request after the users already received, until it holds as many distinct users as the upstream reports in `total`.
- Each page is checked before the next one is requested. An empty page before `total` is reached, a user id seen twice, more users than `total`, or `total` changing between pages stops the request with a 502.
- DummyJSON also accepts `limit=0` to return everything at once. That was not used: the exercise asks for paging, and the loop works whatever page size the upstream serves.

**Publishing only five fields.**
- The `User` model declares the five published fields. Upstream records are parsed into it as they arrive, so every other field is discarded at the boundary and cannot reach a consumer. DummyJSON's synthetic records include passwords, card numbers and addresses.
- The upstream request also uses `select` to ask for those fields only, but the service does not depend on it.

**Strict validation.** Pydantic's strict mode rejects a value of the wrong type instead of converting it; for example, an `id` of `"1"` is an error rather than `1`. Upstream values are therefore passed through unchanged, or the request fails.

**Filtering in the service.**
- DummyJSON's `/users/filter` matches one field per request and is documented as case-sensitive, and `total` must be the count before filtering. So the service retrieves every user and filters in memory.
- Matching is exact and case-insensitive, using `casefold()`, which also handles names such as "Straße".
- An empty or whitespace-only filter counts as not supplied.

**Failing clearly.**
- If any page fails, the whole request fails, so a partial list is never returned with `200 OK`. A timeout is a `504 Gateway Timeout`; anything else that goes wrong upstream is a `502 Bad Gateway`. Both mean the problem lies with a service this one depends on, not with the consumer's request or this service itself.
- Error messages are fixed strings. They never include upstream response bodies or the values that failed validation.
- Each failure is logged as a warning with the same message.

**A synchronous route.** FastAPI runs ordinary `def` routes in a thread pool, which suits the blocking httpx client. An async route could serve more concurrent requests while each waits on the upstream, but there is no such requirement here, so the simpler model was kept.

**Testing at the HTTP boundary.**
- The tests replace DummyJSON with httpx's `MockTransport`, so the service's own paging, validation and error handling run in every test.
- The fake serves records that include fields the API must not return, and can inject a fault on a chosen request, such as an error on the second page after the first succeeded.

## Assumptions

- Name filters are exact, whole-value and case-insensitive, after trimming surrounding whitespace from the query value.
- An empty or whitespace-only filter value means the filter was not supplied.
- Unknown query parameters are ignored.
- `total` is the upstream's own total; `count` is the number of users returned after filtering.
- Users are returned in upstream order.
- Upstream values are passed through unchanged; wrong types are rejected rather than converted.
- Data is fetched fresh on every request. Nothing is cached.

## Limitations

- Every request fetches every page from the upstream.
- There is no overall deadline for a request. The timeout limits each connect, read, write and pool wait, so a slow upstream can make a request take longer than the timeout value.
- The `total` check detects some changes to the dataset during a request, not all. A user removed and another added between pages would go unnoticed.
- There is no authentication or rate limiting.

## Production considerations

Three changes would matter most for a production integration service, each with a cost:

- **Caching with an expiry.** If the agreed freshness requirements permit it, caching the retrieved list would cut upstream calls and response times. The cost is that consumers may see data up to one expiry period old, so the expiry would be set with the data owner.
- **Retries with backoff.** Retrying timeouts and 5xx responses on these read-only requests would recover brief upstream failures. Retries add delay and upstream load, so they would be capped and kept within an overall deadline for the request.
- **Monitoring.** Structured logs with a request id, plus metrics for upstream latency and error rate with alerts, so failures are noticed and diagnosed quickly, without logging personal data.

Beyond these:
- The service would sit behind an API gateway, such as Gravitee, for authentication, rate limiting and publishing its OpenAPI specification. It would run as a container with health checks.
- At much larger scale, it would page its own responses rather than load every user on each request.
- The upstream client would move from httpx to httpx2, the maintained continuation of httpx, which Starlette's test client already uses.

## Project structure

```
app/
  main.py          FastAPI application: configuration, GET /users, error responses
  dummyjson.py     DummyJSON client: paging, validation and upstream errors
  users.py         User and response models, name filtering
tests/
  fakes.py         In-memory DummyJSON used by the offline tests
  conftest.py      Test fixtures
  test_users_api.py       Endpoint behaviour: retrieval, filtering, failures, paging checks
  test_filtering.py       Name-matching rules on their own
  test_startup.py         Startup wiring and shutdown, run offline
  test_live_dummyjson.py  Contract tests against the real API (pytest -m live)
```
