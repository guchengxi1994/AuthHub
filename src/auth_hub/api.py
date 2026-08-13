"""Optional FastAPI adapter. Install with ``pip install auth-hub[web]``."""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.responses import JSONResponse
except ImportError as error:  # pragma: no cover
    FastAPI = None  # type: ignore
    JSONResponse = None  # type: ignore
    _FASTAPI_ERROR = error

from .application import AuthHub
from .domain.errors import AuthHubError, AuthorizationError


def create_app(auth_hub: Optional[AuthHub] = None) -> Any:
    if FastAPI is None: raise RuntimeError("FastAPI is optional. Install auth-hub[web] to use create_app().") from _FASTAPI_ERROR
    hub = auth_hub or AuthHub.in_memory()
    app = FastAPI(title="AuthHub", version="0.1.0")

    @app.exception_handler(AuthHubError)
    async def domain_error_handler(_, error: AuthHubError):
        status = 400 if error.code in {"VALIDATION_ERROR", "INVALID_CREDENTIALS", "CONFLICT"} else 401 if error.code in {"TOKEN_INVALID", "UNAUTHENTICATED", "USER_DISABLED", "USER_NOT_FOUND"} else 403 if error.code == "PERMISSION_DENIED" else 404 if error.code and error.code.endswith("_NOT_FOUND") else 400
        return JSONResponse(status_code=status, content={"code": error.code, "message": str(error), "details": error.details})

    @app.get("/health")
    async def health() -> Dict[str, str]: return {"status": "ok"}

    @app.post("/api/auth/login")
    async def login(payload: Dict[str, Any]): return hub.login(str(payload.get("username", "")), str(payload.get("password", "")))

    @app.post("/api/auth/refresh")
    async def refresh(payload: Dict[str, Any]): return hub.refresh(str(payload.get("refresh_token") or payload.get("refreshToken") or ""))

    @app.post("/api/auth/logout")
    async def logout(authorization: Optional[str] = Header(None)):
        hub.logout(_bearer(authorization)); return {"success": True}

    @app.get("/api/auth/me")
    async def me(authorization: Optional[str] = Header(None)): return hub.user_dict(hub.authenticate(_bearer(authorization)))

    @app.post("/api/auth/check")
    async def check(payload: Dict[str, Any], authorization: Optional[str] = Header(None)): return hub.check_permission(_bearer(authorization), str(payload.get("permission", "")), resource=payload.get("resource"), context=payload.get("context")).to_dict()

    @app.post("/api/auth/check/batch")
    async def check_batch(payload: Dict[str, Any], authorization: Optional[str] = Header(None)): return {"results": [result.to_dict() for result in hub.check_permissions(_bearer(authorization), payload.get("permissions", []), resource=payload.get("resource"), context=payload.get("context"))]}

    @app.post("/api/auth/check-token")
    async def check_token(authorization: Optional[str] = Header(None)): return hub.user_dict(hub.authenticate(_bearer(authorization)))

    @app.get("/api/auth/user-permissions")
    async def user_permissions(authorization: Optional[str] = Header(None)): return {"permissions": hub.user_permissions(hub.authenticate(_bearer(authorization)).id)}

    @app.get("/api/users")
    async def list_users(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.user_dict(item) for item in hub.list_users()]}

    @app.post("/api/users")
    async def create_user(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return hub.user_dict(hub.create_user(str(payload.get("username", "")), str(payload.get("password", "")), display_name=str(payload.get("display_name", "")), email=payload.get("email")))

    @app.patch("/api/users/{user_id}")
    async def update_user(user_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return hub.user_dict(hub.update_user(user_id, display_name=payload.get("display_name"), email=payload.get("email"), enabled=payload.get("enabled")))

    @app.get("/api/organizations")
    async def list_organizations(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.organization_dict(item) for item in hub.list_organizations()], "tree": hub.organization_tree()}

    @app.post("/api/organizations")
    async def create_organization(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        org = hub.create_organization(str(payload.get("name", "")), parent_id=payload.get("parent_id"), description=payload.get("description"))
        return hub.organization_dict(org)

    @app.get("/api/roles")
    async def list_roles(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.role_dict(item) for item in hub.list_roles()]}

    @app.post("/api/roles")
    async def create_role(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return hub.role_dict(hub.create_role(str(payload.get("code", "")), str(payload.get("name", "")), description=payload.get("description")))

    @app.post("/api/users/{user_id}/roles/{role_id}")
    async def assign_role(user_id: str, role_id: str, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization); hub.assign_role(user_id, role_id); return {"success": True}

    @app.post("/api/roles/{role_id}/permissions/{permission_code:path}")
    async def assign_permission(role_id: str, permission_code: str, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization); hub.assign_permission(role_id, permission_code); return {"success": True}

    @app.get("/api/permissions")
    async def list_permissions(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.permission_dict(item) for item in hub.list_permissions()]}

    @app.post("/api/modules/register")
    async def register_module(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = hub.authenticate(_bearer(authorization))
        if not actor.is_super_admin:
            raise AuthorizationError("SYSTEM_ADMIN_REQUIRED")
        return hub.register_module(str(payload.get("module_id") or payload.get("moduleId") or ""), str(payload.get("module_name") or payload.get("moduleName") or ""), description=payload.get("description"), permissions=payload.get("permissions"), apis=payload.get("apis"), resources=payload.get("resources"), metadata=payload.get("metadata")).to_dict()

    app.state.auth_hub = hub
    return app


def _require_admin(hub: AuthHub, authorization: Optional[str]) -> None:
    actor = hub.authenticate(_bearer(authorization))
    if not actor.is_super_admin:
        raise AuthorizationError("SYSTEM_ADMIN_REQUIRED")


def _bearer(value: Optional[str]) -> str:
    if not value or not value.lower().startswith("bearer "): return ""
    return value[7:].strip()
