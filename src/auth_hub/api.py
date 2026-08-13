"""Optional FastAPI adapter. Install with ``pip install auth-hub[web]``."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from fastapi import FastAPI, Header
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as error:  # pragma: no cover
    FastAPI = None  # type: ignore
    JSONResponse = None  # type: ignore
    _FASTAPI_ERROR = error

from .application import AuthHub, AuthHubSettings
from .domain.errors import AuthHubError, AuthorizationError
from .ports.services import Cache


WEB_ROOT = Path(__file__).with_name("web")


def create_app(auth_hub: Optional[AuthHub] = None, *, database_path: str = "authhub.db", cache: Optional[Cache] = None, settings: AuthHubSettings = AuthHubSettings()) -> Any:
    if FastAPI is None: raise RuntimeError("FastAPI is optional. Install auth-hub[web] to use create_app().") from _FASTAPI_ERROR
    hub = auth_hub or AuthHub.local(database_path, settings, cache=cache)
    app = FastAPI(title="AuthHub", version="0.1.0")
    app.mount("/admin/assets", StaticFiles(directory=str(WEB_ROOT / "static")), name="admin-assets")

    @app.exception_handler(AuthHubError)
    async def domain_error_handler(_, error: AuthHubError):
        status = 409 if error.code == "CONFLICT" else 422 if error.code == "VALIDATION_ERROR" else 401 if error.code in {"INVALID_CREDENTIALS", "TOKEN_INVALID", "UNAUTHENTICATED", "USER_DISABLED", "USER_NOT_FOUND"} else 403 if error.code in {"PERMISSION_DENIED", "SYSTEM_ADMIN_REQUIRED"} else 404 if error.code and error.code.endswith("_NOT_FOUND") else 400
        return JSONResponse(status_code=status, content={"code": error.code, "message": str(error), "details": error.details})

    @app.get("/health")
    async def health() -> Dict[str, str]: return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def root(): return RedirectResponse(url="/admin")

    @app.get("/admin", include_in_schema=False)
    async def admin(): return FileResponse(WEB_ROOT / "templates" / "admin.html")

    @app.get("/api/admin/overview")
    async def admin_overview(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"users": len(hub.list_users()), "organizations": len(hub.list_organizations()), "roles": len(hub.list_roles()), "permissions": len(hub.list_permissions()), "modules": len(hub.list_modules()), "resources": len(hub.list_resources()), "audit_events": len(hub.list_audit_events(limit=500))}

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
        actor = _require_admin(hub, authorization)
        return hub.user_dict(hub.create_user(str(payload.get("username", "")), str(payload.get("password", "")), display_name=str(payload.get("display_name", "")), email=payload.get("email"), organization_ids=payload.get("organization_ids") or [], role_ids=payload.get("role_ids") or [], actor_id=actor.id))

    @app.patch("/api/users/{user_id}")
    async def update_user(user_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        return hub.user_dict(hub.update_user(user_id, display_name=payload.get("display_name"), email=payload.get("email"), enabled=payload.get("enabled"), actor_id=actor.id))

    @app.delete("/api/users/{user_id}")
    async def delete_user(user_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        return hub.user_dict(hub.delete_user(user_id, actor_id=actor.id))

    @app.get("/api/users/{user_id}/roles")
    async def user_roles(user_id: str, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.role_dict(item) for item in hub.user_roles(user_id)]}

    @app.get("/api/users/{user_id}/organizations")
    async def user_organizations(user_id: str, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.organization_dict(item) for item in hub.user_organizations(user_id)]}

    @app.post("/api/users/{user_id}/organizations/{organization_id}")
    async def assign_organization(user_id: str, organization_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.assign_organization(user_id, organization_id, actor_id=actor.id); return {"success": True}

    @app.delete("/api/users/{user_id}/organizations/{organization_id}")
    async def remove_organization(user_id: str, organization_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.remove_organization(user_id, organization_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/organizations")
    async def list_organizations(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.organization_dict(item) for item in hub.list_organizations()], "tree": hub.organization_tree()}

    @app.post("/api/organizations")
    async def create_organization(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        org = hub.create_organization(str(payload.get("name", "")), parent_id=payload.get("parent_id"), description=payload.get("description"), actor_id=actor.id)
        return hub.organization_dict(org)

    @app.patch("/api/organizations/{organization_id}")
    async def update_organization(organization_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        changes = {"name": payload.get("name"), "description": payload.get("description"), "enabled": payload.get("enabled"), "actor_id": actor.id}
        if "parent_id" in payload: changes["parent_id"] = payload["parent_id"]
        return hub.organization_dict(hub.update_organization(organization_id, **changes))

    @app.delete("/api/organizations/{organization_id}")
    async def delete_organization(organization_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.delete_organization(organization_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/roles")
    async def list_roles(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.role_dict(item) for item in hub.list_roles()]}

    @app.post("/api/roles")
    async def create_role(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        return hub.role_dict(hub.create_role(payload.get("code"), str(payload.get("name", "")), description=payload.get("description"), actor_id=actor.id))

    @app.patch("/api/roles/{role_id}")
    async def update_role(role_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        return hub.role_dict(hub.update_role(role_id, name=payload.get("name"), description=payload.get("description"), enabled=payload.get("enabled"), actor_id=actor.id))

    @app.delete("/api/roles/{role_id}")
    async def delete_role(role_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.delete_role(role_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/roles/{role_id}/permissions")
    async def role_permissions(role_id: str, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.permission_dict(item) for item in hub.role_permissions(role_id)]}

    @app.post("/api/users/{user_id}/roles/{role_id}")
    async def assign_role(user_id: str, role_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.assign_role(user_id, role_id, actor_id=actor.id); return {"success": True}

    @app.delete("/api/users/{user_id}/roles/{role_id}")
    async def remove_role(user_id: str, role_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.remove_role(user_id, role_id, actor_id=actor.id); return {"success": True}

    @app.post("/api/roles/{role_id}/permissions/{permission_code:path}")
    async def assign_permission(role_id: str, permission_code: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.assign_permission(role_id, permission_code, actor_id=actor.id); return {"success": True}

    @app.delete("/api/roles/{role_id}/permissions/{permission_code:path}")
    async def remove_permission(role_id: str, permission_code: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.remove_permission(role_id, permission_code, actor_id=actor.id); return {"success": True}

    @app.get("/api/permissions")
    async def list_permissions(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.permission_dict(item) for item in hub.list_permissions()]}

    @app.post("/api/permissions")
    async def create_permission(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        permission = hub.create_permission(payload.get("code"), str(payload.get("name", "")), description=payload.get("description"), kind=str(payload.get("kind", "operation")), module_id=payload.get("module_id"), resource_id=payload.get("resource_id"), action=payload.get("action"), role_ids=payload.get("role_ids") or [], metadata=payload.get("metadata"), actor_id=actor.id)
        return hub.permission_dict(permission)

    @app.patch("/api/permissions/{permission_code:path}")
    async def update_permission(permission_code: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        return hub.permission_dict(hub.update_permission(permission_code, name=payload.get("name"), description=payload.get("description"), enabled=payload.get("enabled"), metadata=payload.get("metadata"), actor_id=actor.id))

    @app.get("/api/modules")
    async def list_modules(authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [item.to_dict() for item in hub.list_modules()]}

    @app.get("/api/modules/{module_id}")
    async def get_module(module_id: str, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return hub.get_module(module_id).to_dict()

    @app.get("/api/resources")
    async def list_resources(module_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.resource_dict(item) for item in hub.list_resources(module_id)]}

    @app.post("/api/resources")
    async def create_resource(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        return hub.resource_dict(hub.create_resource(str(payload.get("module_id") or ""), str(payload.get("resource_type") or ""), str(payload.get("resource_key") or ""), str(payload.get("name") or ""), metadata=payload.get("metadata"), actor_id=actor.id))

    @app.delete("/api/resources/{resource_id}")
    async def delete_resource(resource_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization)
        hub.delete_resource(resource_id, actor_id=actor.id)
        return {"success": True}

    @app.delete("/api/modules/{module_id}")
    async def delete_module(module_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_admin(hub, authorization); hub.delete_module(module_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/audit-events")
    async def list_audit_events(limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None, authorization: Optional[str] = Header(None)):
        _require_admin(hub, authorization)
        return {"items": [hub.audit_event_dict(event) for event in hub.list_audit_events(limit=limit, actor_id=actor_id, action=action)]}

    @app.post("/api/modules/register")
    async def register_module(payload: Dict[str, Any], authorization: Optional[str] = Header(None), x_auth_hub_registration_key: Optional[str] = Header(None)):
        actor_id = _module_registrar_actor(hub, authorization, x_auth_hub_registration_key)
        return hub.register_module(payload.get("module_id") or payload.get("moduleId"), str(payload.get("module_name") or payload.get("moduleName") or ""), description=payload.get("description"), permissions=payload.get("permissions"), apis=payload.get("apis"), resources=payload.get("resources"), metadata=payload.get("metadata"), actor_id=actor_id).to_dict()

    app.state.auth_hub = hub
    return app


def _require_admin(hub: AuthHub, authorization: Optional[str]):
    actor = hub.authenticate(_bearer(authorization))
    if not actor.is_super_admin:
        raise AuthorizationError("SYSTEM_ADMIN_REQUIRED")
    return actor


def _module_registrar_actor(hub: AuthHub, authorization: Optional[str], registration_key: Optional[str]) -> str:
    configured_key = hub.settings.module_registration_key
    if configured_key and registration_key and hmac.compare_digest(configured_key, registration_key):
        return "service:module-registration"
    return _require_admin(hub, authorization).id


def _bearer(value: Optional[str]) -> str:
    if not value or not value.lower().startswith("bearer "): return ""
    return value[7:].strip()
