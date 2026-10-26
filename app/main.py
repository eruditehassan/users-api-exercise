"""HTTP API: GET /users returns every DummyJSON user in a consistent, filterable form."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.dummyjson import DummyJsonClient, UpstreamError, UpstreamTimeout
from app.users import UsersResponse, filter_users

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create one upstream HTTP client at startup, so connections are reused, and close it at shutdown."""
    # Uvicorn configures only its own loggers; this gives the service's warnings a level and timestamp.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    summary="Retrieves every user from DummyJSON and returns them in a consistent, filterable form.",
    version="1.0.0",
    lifespan=lifespan,
)


class ErrorResponse(BaseModel):
    """Body of every error response, matching FastAPI's own error shape."""

    detail: str


def get_dummyjson(request: Request) -> DummyJsonClient:
    """Provide the shared upstream client. Tests replace this dependency with a fake."""
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
    """Return every upstream user, optionally filtered by first name, last name or both.

    When both filters are supplied, a user must match both. `total` is the upstream
    count before filtering; `count` is the number of users in this response.
    """
    total, users = client.fetch_all_users()
    matched = filter_users(users, firstName, lastName)
    return UsersResponse(total=total, count=len(matched), users=matched)


@app.exception_handler(UpstreamError)
async def handle_upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
    """Turn an upstream failure into 504 (timeout) or 502 (anything else). No partial data is returned."""
    if isinstance(exc, UpstreamTimeout):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        status_code = status.HTTP_502_BAD_GATEWAY
    # The message is a fixed string from this service, so it is safe to log: no user data or upstream body.
    logger.warning("%s %s failed with %d: %s", request.method, request.url.path, status_code, exc)
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})
