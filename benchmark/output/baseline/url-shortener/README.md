# URL Shortener

A small, well-structured URL shortener HTTP API built with FastAPI.

## Features

- **Shorten** a URL into a short code
- **Redirect** from a short code to the original URL
- **Click stats** per short code
- **Rate limiting** per client (sliding window)

## Architecture

The code is split into single-responsibility modules, each independently testable:

| Module | Responsibility |
| --- | --- |
| `app/config.py` | Settings & named constants (no magic numbers); env overrides via `URLSHORT_*` |
| `app/codec.py` | base62 short-code generation (`secrets`-backed, not guessable) |
| `app/repository.py` | Storage abstraction (`LinkRepository` Protocol) + in-memory implementation |
| `app/rate_limiter.py` | Sliding-window rate limiter with an injectable clock |
| `app/service.py` | Business logic: unique-code retry, click accounting |
| `app/models.py` | Pydantic request/response contracts |
| `app/main.py` | `create_app()` factory + HTTP routes |

Dependencies are injected through `create_app()`, which keeps the app
configurable and the tests fast and deterministic (e.g. a fake clock for the
rate limiter, strict limits in tests).

## API

| Method | Path | Description | Success |
| --- | --- | --- | --- |
| `POST` | `/shorten` | Body `{"url": "https://…"}` → `{short_code, short_url, url}` | `201` |
| `GET` | `/{short_code}` | Redirect to the original URL (counts a click) | `307` |
| `GET` | `/stats/{short_code}` | `{short_code, url, clicks, created_at}` | `200` |
| `GET` | `/health` | Liveness probe | `200` |

Errors: invalid/non-http URL → `422`, unknown code → `404`, over rate limit →
`429` with a `Retry-After` header.

Interactive docs are served at `/docs` once running.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Example:

```bash
curl -X POST localhost:8000/shorten -H 'Content-Type: application/json' \
     -d '{"url":"https://www.example.com/some/long/path"}'
# {"short_code":"NlvXPHR","short_url":"http://localhost:8000/NlvXPHR","url":"…"}

curl -i localhost:8000/NlvXPHR        # 307 redirect
curl localhost:8000/stats/NlvXPHR     # {"clicks":1, …}
```

## Configuration

All settings have defaults and can be overridden via environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `URLSHORT_BASE_URL` | `http://localhost:8000` | Base used to build `short_url` |
| `URLSHORT_SHORT_CODE_LENGTH` | `7` | Length of generated codes |
| `URLSHORT_MAX_CODE_GENERATION_ATTEMPTS` | `10` | Collision-retry budget |
| `URLSHORT_RATE_LIMIT_MAX_REQUESTS` | `100` | Requests allowed per window |
| `URLSHORT_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window length |

## Tests

Built test-first (TDD). Run the suite with coverage (gate: ≥80%, currently 100%):

```bash
pytest
```

## Notes & limitations

- Storage is in-memory, so data resets on restart. The `LinkRepository`
  Protocol is the seam for a database-backed implementation.
- Rate limiting keys on `request.client.host`. Behind a proxy/load balancer
  you would key on a trusted `X-Forwarded-For` instead.
