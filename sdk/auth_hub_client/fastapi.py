from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Optional

try:
    from fastapi import Header, HTTPException, Request
except ImportError as error:  # pragma: no cover
    Header = HTTPException = Request = None  # type: ignore
    _FASTAPI_ERROR = error

from .client import AuthHubClient


class AuthHubFastAPI:
    def __init__(self, client: AuthHubClient) -> None:
        if HTTPException is None: raise RuntimeError("Install auth-hub-client[fastapi] to use FastAPI integration") from _FASTAPI_ERROR
        self.client = client

    def require(self, permission: str, *, resource: Optional[str] = None, resource_instance_id: Optional[str] = None) -> Callable[..., Mapping[str, Any]]:
        async def dependency(authorization: Optional[str] = Header(None)) -> Mapping[str, Any]:
            token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
            try:
                context = {"resource_instance_id": resource_instance_id} if resource_instance_id else None
                return await asyncio.to_thread(self.client.check_or_raise, token, permission, resource=resource, context=context)
            except Exception as error:
                if getattr(error, "status_code", None) in {401, 403}: raise HTTPException(status_code=error.status_code, detail=str(error)) from error
                raise HTTPException(status_code=503, detail="AuthHub unavailable") from error
        return dependency

    def require_resource(self, permission: str, resource_id: str, external_id_parameter: str, *, context: Optional[Mapping[str, Any]] = None) -> Callable[..., Mapping[str, Any]]:
        """Authorize a business record using a FastAPI route path parameter.

        ``external_id_parameter`` must be a named parameter on the route, for
        example ``order_id`` for ``/orders/{order_id}``.
        """
        async def dependency(request: Request, authorization: Optional[str] = Header(None)) -> Mapping[str, Any]:
            token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
            external_id = request.path_params.get(external_id_parameter)
            if external_id is None:
                raise HTTPException(status_code=500, detail=f"route parameter not available: {external_id_parameter}")
            try:
                return await asyncio.to_thread(self.client.check_resource_or_raise, token, permission, resource_id, str(external_id), context=context)
            except Exception as error:
                if getattr(error, "status_code", None) in {401, 403}:
                    raise HTTPException(status_code=error.status_code, detail=str(error)) from error
                raise HTTPException(status_code=503, detail="AuthHub unavailable") from error
        return dependency

    def permission_snapshot(self) -> Callable[..., Mapping[str, Any]]:
        async def dependency(authorization: Optional[str] = Header(None)) -> Mapping[str, Any]:
            token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
            try:
                return await asyncio.to_thread(self.client.user_permissions, token)
            except Exception as error:
                if getattr(error, "status_code", None) == 401: raise HTTPException(status_code=401, detail=str(error)) from error
                raise HTTPException(status_code=503, detail="AuthHub unavailable") from error
        return dependency


def require_permission(client: AuthHubClient, permission: str, *, resource: Optional[str] = None, resource_instance_id: Optional[str] = None) -> Callable[..., Mapping[str, Any]]:
    return AuthHubFastAPI(client).require(permission, resource=resource, resource_instance_id=resource_instance_id)


def require_resource_permission(client: AuthHubClient, permission: str, resource_id: str, external_id_parameter: str, *, context: Optional[Mapping[str, Any]] = None) -> Callable[..., Mapping[str, Any]]:
    return AuthHubFastAPI(client).require_resource(permission, resource_id, external_id_parameter, context=context)
