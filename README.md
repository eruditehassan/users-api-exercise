# Users Integration API

[![CI](https://github.com/eruditehassan/users-api-exercise/actions/workflows/ci.yml/badge.svg)](https://github.com/eruditehassan/users-api-exercise/actions/workflows/ci.yml)

This is my solution to the Integration Developer exercise. It's a small REST API, written in Python with FastAPI, that pulls every user from the [DummyJSON users API](https://dummyjson.com/docs/users), cuts each record down to five fields and lets you filter by first and last name.

There's a running copy at [hassan-bukhari-users-api.vercel.app/docs](https://hassan-bukhari-users-api.vercel.app/docs) and a short write-up at [projects.hassanbukhari.com/users-api](https://projects.hassanbukhari.com/users-api). Everything below also works locally.

## Running it

You'll need Python 3.14 (I developed and tested it on 3.14.7).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

`requirements-dev.txt` includes the test tools. If you only want to run the API, `requirements.txt` is enough.

The API runs on `http://127.0.0.1:8000`. FastAPI also serves interactive docs at `http://127.0.0.1:8000/docs`, which is the quickest way to try the filters.

```bash
curl "http://127.0.0.1:8000/users"
curl "http://127.0.0.1:8000/users?firstName=Emily"
curl "http://127.0.0.1:8000/users?lastName=Smith"
curl "http://127.0.0.1:8000/users?firstName=Emily&lastName=Smith"
```

For example, `GET /users?firstName=emily&lastName=JOHNSON` currently returns:

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

`total` is the number of users DummyJSON reports before filtering; `count` is how many are in the response.

## Running the tests

```bash
pytest
```

The tests don't touch the network. I replaced DummyJSON with a small fake built on httpx's `MockTransport`, so the real paging, validation and error-handling code still runs, just against data I control. That makes it easy to test things like the second page failing after the first one worked, or the upstream sending the same page twice.

There are also two tests that call the real DummyJSON API, to check it still behaves the way the fake assumes. They're excluded by default; run them with:

```bash
pytest -m live
```

## How it's deployed

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the offline tests on every pull request and every push to `main`.
- A push to `main` deploys to Vercel only if those tests pass.
- Vercel's own Git deployments are switched off in `vercel.json`, so a commit can't reach production any other way.
- After deploying, the workflow checks that the service responds and then makes one real `/users` request. That last check goes through to DummyJSON, so if it fails the run shows a warning rather than failing. A DummyJSON outage isn't a problem with the deployment.

The hosted copy is a demonstration on Vercel, not a production service, so the first request after a quiet spell can be slower while it starts up.

## Configuration

Everything has a default, so none of these need setting:

| Variable | Default | What it does |
|---|---|---|
| `UPSTREAM_BASE_URL` | `https://dummyjson.com` | Where the users API lives |
| `UPSTREAM_TIMEOUT_SECONDS` | `5` | httpx timeout for each connect, read and write |
| `UPSTREAM_PAGE_SIZE` | `100` | Users requested per page |

## How it works

### Getting every user

`app/dummyjson.py` does the upstream work.
- It asks for 100 users at a time with `limit` and `skip`, starting each request after the users it already has, until it holds as many as DummyJSON reports in `total`.
- Before asking for the next page, it checks the one it just got. If anything doesn't add up, the request fails rather than returning a list that might be incomplete. That means:
  - an empty page before everyone has arrived
  - the same user id twice
  - more users than `total`
  - `total` changing partway through

DummyJSON will also return everything in one go with `limit=0`. I didn't use that. The exercise is clear that a single response shouldn't be assumed to hold the full dataset, and paging keeps working whatever page size the upstream decides to serve.

### Keeping five fields

`app/users.py` has a `User` model with just the five fields.
- Upstream records are parsed straight into it, so everything else is dropped as soon as it arrives. DummyJSON's (synthetic) records include passwords, card numbers and addresses.
- I turned on Pydantic's strict mode, so a wrong type, such as an id sent as the string `"1"`, is treated as an error instead of being quietly converted.
- I also send DummyJSON's `select` parameter so it only sends the fields I need, but nothing depends on that.

### Filtering

Filtering happens in this service rather than through DummyJSON's `/users/filter` endpoint, which takes one field at a time and is case-sensitive.
- Names have to match exactly, ignoring case; I used `casefold()` rather than `lower()`.
- When both filters are given, a user has to match both.
- No match is still a normal `200` with `count` 0 and an empty list.

### When the upstream goes wrong

If anything fails on any page, the whole request fails:

- a timeout returns **504 Gateway Timeout**
- an error status, a connection failure, or a response that's malformed or inconsistent returns **502 Bad Gateway**

I used 502/504 rather than 500 because the problem is with the service this one depends on, not with this service.

The body is `{"detail": "..."}` with a short fixed message, for example `"Upstream user service returned HTTP 500"`. It never includes the upstream's response or the values that failed validation. Each failure is logged as one warning line, with no names or query strings in it.

### Sync rather than async

The route is a plain `def`, which FastAPI runs in a thread pool, and that suits the synchronous httpx client. Async would help with a lot of concurrent requests, but nothing here needs that, and the sync version is simpler to follow.

## Assumptions

- "Filter by first name" means an exact match on the whole name, ignoring case and surrounding spaces. So `Em` doesn't match Emily.
- An empty filter such as `?firstName=` is treated as no filter.
- Unknown query parameters are ignored.
- Users come back in the order DummyJSON returns them.
- Values are passed through as they are. I don't reformat phone numbers or validate emails, since this service doesn't own the data.
- Data is fetched fresh on every request.

## Limitations

- Every request fetches all the pages from DummyJSON, which is three requests at the moment.
- The timeout applies to each connect, read and write rather than the whole request. There's no overall deadline, so a slow upstream can make a request take longer than 5 seconds.
- The `total` check catches users being added or removed mid-request, but not one being removed and another added between pages.
- There's no authentication or rate limiting.

## What I'd change for production

These are the three things I'd look at first, each with a trade-off:

- **Caching.** If the freshness requirements allow it, caching the user list for a short time would cut the upstream calls and make responses much faster. The cost is that consumers could see data up to one expiry period old, so the expiry would need agreeing with whoever owns the data.
- **Retries.** These are read-only requests, so retrying timeouts and 5xx errors with backoff would ride out short upstream blips. Retries add latency and extra load on the upstream, so I'd cap them and put an overall deadline on the request.
- **Monitoring.** Structured logs with a request id, plus metrics for upstream latency and error rates with alerts on them, so problems get noticed quickly. Again, without logging personal data.

Beyond that:
- I'd put it behind an API gateway such as Gravitee for authentication, rate limiting and publishing the OpenAPI spec, and run it as a container with health checks.
- If the dataset got much bigger, I'd sync users into a local store and page our own responses instead of loading everyone on every request.
- I'd move the client from httpx to httpx2, the maintained continuation of httpx that Starlette's test client already uses.

## Project layout

```
.github/workflows/ci.yml   tests on every push and pull request; deploys main after they pass
vercel.json      turns off Vercel's own Git deployments
app/
  main.py          FastAPI app, GET /users and error handling
  dummyjson.py     DummyJSON client: paging, validation, upstream errors
  users.py         User and response models, filtering
tests/
  fakes.py         fake DummyJSON used by the tests
  conftest.py      fixtures
  test_users_api.py       endpoint tests
  test_filtering.py       filtering rules on their own
  test_startup.py         startup and shutdown wiring
  test_live_dummyjson.py  checks against the real API (pytest -m live)
```
