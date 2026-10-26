"""FastAPI app exposing GET /users."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.dummyjson import DummyJsonClient, UpstreamError, UpstreamTimeout
from app.users import UsersResponse, filter_users

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """One shared HTTP client for the app's lifetime, so connections are reused."""
    # Uvicorn only configures its own loggers, so give ours a level and timestamp.
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    http = httpx.Client(
        base_url=os.environ.get("UPSTREAM_BASE_URL", "https://dummyjson.com"),
        timeout=float(os.environ.get("UPSTREAM_TIMEOUT_SECONDS", "5")),
    )
    app.state.dummyjson = DummyJsonClient(
        http, page_size=int(os.environ.get("UPSTREAM_PAGE_SIZE", "100"))
    )
    try:
        yield
    finally:
        http.close()


app = FastAPI(
    title="Users Integration API",
    summary="Every DummyJSON user, trimmed to five fields and filterable by name.",
    version="1.0.0",
    lifespan=lifespan,
)


class ErrorResponse(BaseModel):
    """Same shape as FastAPI's own error responses."""

    detail: str


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


def get_dummyjson(request: Request) -> DummyJsonClient:
    """Overridden in the tests."""
    return request.app.state.dummyjson


@app.get(
    "/users",
    response_model=UsersResponse,
    summary="List users",
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "The upstream API failed or returned an unexpected response.",
        },
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "model": ErrorResponse,
            "description": "The upstream API did not respond in time.",
        },
    },
)
def list_users(
    client: Annotated[DummyJsonClient, Depends(get_dummyjson)],
    firstName: Annotated[
        str | None, Query(description="Exact first name to match, case-insensitive.")
    ] = None,
    lastName: Annotated[
        str | None, Query(description="Exact last name to match, case-insensitive.")
    ] = None,
) -> UsersResponse:
    """Every upstream user, optionally filtered by first name, last name or both.

    When both filters are given, a user has to match both. `total` is DummyJSON's
    count before filtering; `count` is the number of users returned.
    """
    total, users = client.fetch_all_users()
    matched = filter_users(users, firstName, lastName)
    return UsersResponse(total=total, count=len(matched), users=matched)


@app.exception_handler(UpstreamError)
async def handle_upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
    """504 for a timeout, 502 for anything else. Never a partial result."""
    if isinstance(exc, UpstreamTimeout):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        status_code = status.HTTP_502_BAD_GATEWAY
    # exc's message is one of our fixed strings, so this never logs user data.
    logger.warning("%s %s failed with %d: %s", request.method, request.url.path, status_code, exc)
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})
