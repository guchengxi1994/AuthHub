from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Optional

try:
    from fastapi import Header, HTTPException
except ImportError as error:  # pragma: no cover
    Header = HTTPException = None  # type: ignore
    _FASTAPI_ERROR = error

from .client import AuthHubClient


class AuthHubFastAPI:
    def __init__(self, client: AuthHubClient) -> None:
        if HTTPException is None: raise RuntimeError("Install auth-hub-client[fastapi] to use FastAPI integration") from _FASTAPI_ERROR
        self.client = client

    def require(self, permission: str, *, resource: Optional[str] = None) -> Callable[..., Mapping[str, Any]]:
        async def dependency(authorization: Optional[str] = Header(None)) -> Mapping[str, Any]:
            token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
            try:
                return await asyncio.to_thread(self.client.check_or_raise, token, permission, resource=resource)
            except Exception as error:
                if getattr(error, "status_code", None) in {401, 403}: raise HTTPException(status_code=error.status_code, detail=str(error)) from error
                raise HTTPException(status_code=503, detail="AuthHub unavailable") from error
        return dependency


def require_permission(client: AuthHubClient, permission: str, *, resource: Optional[str] = None) -> Callable[..., Mapping[str, Any]]:
    return AuthHubFastAPI(client).require(permission, resource=resource)
