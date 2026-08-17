"""Optional FastAPI adapter. Install with ``pip install auth-hub[web]``."""

from __future__ import annotations

import hmac
import logging
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

from .application import AUTHHUB_SYSTEM_MODULE_ID, AuthHub, AuthHubSettings, authhub_system_permission
from .domain.errors import AuthHubError, AuthorizationError, NotFoundError, ValidationError
from .ports.services import Cache
from .version import VERSION, runtime_release


WEB_ROOT = Path(__file__).with_name("web")
logger = logging.getLogger(__name__)


def create_app(auth_hub: Optional[AuthHub] = None, *, database_path: str = "authhub.db", cache: Optional[Cache] = None, settings: AuthHubSettings = AuthHubSettings()) -> Any:
    if FastAPI is None: raise RuntimeError("FastAPI is optional. Install auth-hub[web] to use create_app().") from _FASTAPI_ERROR
    hub = auth_hub or AuthHub.local(database_path, settings, cache=cache)
    app = FastAPI(title="AuthHub", version=VERSION)
    app.mount("/admin/assets", StaticFiles(directory=str(WEB_ROOT / "static")), name="admin-assets")

    @app.exception_handler(AuthHubError)
    async def domain_error_handler(_, error: AuthHubError):
        status = 409 if error.code == "CONFLICT" else 422 if error.code == "VALIDATION_ERROR" else 401 if error.code in {"INVALID_CREDENTIALS", "TOKEN_INVALID", "UNAUTHENTICATED", "USER_DISABLED", "USER_NOT_FOUND"} else 403 if error.code in {"PERMISSION_DENIED", "SYSTEM_ADMIN_REQUIRED"} else 404 if error.code and error.code.endswith("_NOT_FOUND") else 400
        return JSONResponse(status_code=status, content={"code": error.code, "message": str(error), "details": error.details})

    @app.get("/health")
    async def health() -> Dict[str, str]: return {"status": "ok"}

    @app.get("/api/meta", include_in_schema=False)
    async def runtime_metadata() -> Dict[str, str]: return runtime_release()

    @app.get("/", include_in_schema=False)
    async def root(): return RedirectResponse(url="/admin")

    @app.get("/admin", include_in_schema=False)
    async def admin(): return FileResponse(WEB_ROOT / "templates" / "admin.html")

    @app.get("/api/admin/overview")
    async def admin_overview(authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "page", "admin", "view")
        return {"users": len(hub.list_users()), "organizations": len(hub.list_organizations()), "roles": len(hub.list_roles()), "permissions": len(hub.list_permissions()), "modules": len(hub.list_modules()), "resources": len(hub.list_resources()), "resource_instances": len(hub.repository.list_resource_instances()), "audit_events": len(hub.list_audit_events(limit=500))}

    @app.post("/api/auth/login")
    async def login(payload: Dict[str, Any]): return hub.login(str(payload.get("username", "")), str(payload.get("password", "")))

    @app.post("/api/auth/refresh")
    async def refresh(payload: Dict[str, Any]): return hub.refresh(str(payload.get("refresh_token") or payload.get("refreshToken") or ""))

    @app.post("/api/auth/logout")
    async def logout(authorization: Optional[str] = Header(None)):
        hub.logout(_bearer(authorization)); return {"success": True}

    @app.get("/api/auth/me")
    async def me(authorization: Optional[str] = Header(None)): return hub.user_dict(hub.authenticate(_bearer(authorization)))

    @app.get("/api/auth/users/resolve")
    async def resolve_share_recipient(username: str, authorization: Optional[str] = Header(None)):
        """Resolve one exact username for a resource-owner sharing workflow.

        This deliberately does not expose a browsable user directory. The
        caller must already know the AuthHub username of the intended recipient.
        """
        _require_system_permission(hub, authorization, "custom", "share-recipient", "read")
        user = hub.repository.get_user_by_username(username.strip())
        if not user or not user.enabled:
            raise NotFoundError("user", username)
        return _share_user_dict(user)

    @app.post("/api/auth/check")
    async def check(payload: Dict[str, Any], authorization: Optional[str] = Header(None)): return hub.check_permission(_bearer(authorization), str(payload.get("permission", "")), resource=payload.get("resource"), context=payload.get("context")).to_dict()

    @app.post("/api/auth/check/batch")
    async def check_batch(payload: Dict[str, Any], authorization: Optional[str] = Header(None)): return {"results": [result.to_dict() for result in hub.check_permissions(_bearer(authorization), payload.get("permissions", []), resource=payload.get("resource"), context=payload.get("context"))]}

    @app.post("/api/auth/check-resource")
    async def check_resource(payload: Dict[str, Any], authorization: Optional[str] = Header(None)): return hub.can_access_resource(_bearer(authorization), str(payload.get("permission", "")), str(payload.get("resource_id", "")), str(payload.get("external_id", "")), context=payload.get("context")).to_dict()

    @app.post("/api/service/users/{user_id}/access-checks")
    async def service_user_access_checks(user_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None), x_auth_hub_registration_key: Optional[str] = Header(None, alias="X-AuthHub-Registration-Key")):
        """Service-only batch preflight for one user's global and instance permissions."""
        _module_registrar_actor(hub, authorization, x_auth_hub_registration_key)
        checks = payload.get("checks") or []
        if not isinstance(checks, list) or not checks or len(checks) > 100:
            raise ValidationError("checks must contain between 1 and 100 items")
        results = []
        for index, item in enumerate(checks):
            if not isinstance(item, dict):
                raise ValidationError("each access check must be an object")
            check_id = str(item.get("id") or index)
            permission = str(item.get("permission") or "")
            resource_id = str(item.get("resource_id") or "")
            external_id = str(item.get("external_id") or "")
            if bool(resource_id) != bool(external_id):
                raise ValidationError("resource_id and external_id must be supplied together")
            result = (
                hub.can_user_access_resource(user_id, permission, resource_id, external_id, context=item.get("context"))
                if resource_id else hub.check_permission_for_user(user_id, permission, resource=item.get("resource"), context=item.get("context"))
            )
            results.append({"id": check_id, **result.to_dict()})
        return {"user_id": user_id, "results": results}

    @app.post("/api/auth/check-token")
    async def check_token(authorization: Optional[str] = Header(None)): return hub.user_dict(hub.authenticate(_bearer(authorization)))

    @app.get("/api/auth/user-permissions")
    async def user_permissions(authorization: Optional[str] = Header(None)): return {"permissions": hub.user_permissions(hub.authenticate(_bearer(authorization)).id)}

    @app.get("/api/users")
    async def list_users(query: str = "", limit: Optional[int] = None, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "users", "read")
        users = hub.list_users()
        needle = query.strip().casefold()
        if needle:
            users = [
                item for item in users
                if needle in " ".join((item.username, item.display_name, item.email or "")).casefold()
            ]
        if limit is not None:
            users = users[:max(1, min(limit, 100))]
        return {"items": [hub.user_dict(item) for item in users]}

    @app.post("/api/users")
    async def create_user(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "create")
        for role_id in payload.get("role_ids") or []:
            _require_assignable_role(hub, actor, str(role_id))
        return hub.user_dict(hub.create_user(str(payload.get("username", "")), str(payload.get("password", "")), display_name=str(payload.get("display_name", "")), email=payload.get("email"), organization_ids=payload.get("organization_ids") or [], role_ids=payload.get("role_ids") or [], actor_id=actor.id))

    @app.patch("/api/users/{user_id}")
    async def update_user(user_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "update")
        _require_manageable_user(hub, actor, user_id)
        return hub.user_dict(hub.update_user(user_id, display_name=payload.get("display_name"), email=payload.get("email"), enabled=payload.get("enabled"), actor_id=actor.id))

    @app.delete("/api/users/{user_id}")
    async def delete_user(user_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "delete")
        _require_manageable_user(hub, actor, user_id)
        return hub.user_dict(hub.delete_user(user_id, actor_id=actor.id))

    @app.get("/api/users/{user_id}/roles")
    async def user_roles(user_id: str, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "users", "read")
        return {"items": [hub.role_dict(item) for item in hub.user_roles(user_id)]}

    @app.get("/api/users/{user_id}/organizations")
    async def user_organizations(user_id: str, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "users", "read")
        return {"items": [hub.organization_dict(item) for item in hub.user_organizations(user_id)]}

    @app.post("/api/users/{user_id}/organizations/{organization_id}")
    async def assign_organization(user_id: str, organization_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "update"); _require_manageable_user(hub, actor, user_id); hub.assign_organization(user_id, organization_id, actor_id=actor.id); return {"success": True}

    @app.delete("/api/users/{user_id}/organizations/{organization_id}")
    async def remove_organization(user_id: str, organization_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "update"); _require_manageable_user(hub, actor, user_id); hub.remove_organization(user_id, organization_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/organizations")
    async def list_organizations(authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "organizations", "read")
        return {"items": [hub.organization_dict(item) for item in hub.list_organizations()], "tree": hub.organization_tree()}

    @app.post("/api/organizations")
    async def create_organization(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "organizations", "create")
        org = hub.create_organization(str(payload.get("name", "")), parent_id=payload.get("parent_id"), description=payload.get("description"), actor_id=actor.id)
        return hub.organization_dict(org)

    @app.patch("/api/organizations/{organization_id}")
    async def update_organization(organization_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "organizations", "update")
        changes = {"name": payload.get("name"), "description": payload.get("description"), "enabled": payload.get("enabled"), "actor_id": actor.id}
        if "parent_id" in payload: changes["parent_id"] = payload["parent_id"]
        return hub.organization_dict(hub.update_organization(organization_id, **changes))

    @app.delete("/api/organizations/{organization_id}")
    async def delete_organization(organization_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "organizations", "delete"); hub.delete_organization(organization_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/roles")
    async def list_roles(authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "roles", "read")
        return {"items": [hub.role_dict(item) for item in hub.list_roles()]}

    @app.post("/api/roles")
    async def create_role(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "roles", "create")
        return hub.role_dict(hub.create_role(payload.get("code"), str(payload.get("name", "")), description=payload.get("description"), actor_id=actor.id))

    @app.patch("/api/roles/{role_id}")
    async def update_role(role_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "roles", "update")
        _require_manageable_role(hub, actor, role_id)
        return hub.role_dict(hub.update_role(role_id, name=payload.get("name"), description=payload.get("description"), enabled=payload.get("enabled"), actor_id=actor.id))

    @app.delete("/api/roles/{role_id}")
    async def delete_role(role_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "roles", "delete"); _require_manageable_role(hub, actor, role_id); hub.delete_role(role_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/roles/{role_id}/permissions")
    async def role_permissions(role_id: str, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "roles", "read")
        return {"items": [hub.permission_dict(item) for item in hub.role_permissions(role_id)]}

    @app.post("/api/users/{user_id}/roles/{role_id}")
    async def assign_role(user_id: str, role_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "update"); _require_manageable_user(hub, actor, user_id); _require_assignable_role(hub, actor, role_id); hub.assign_role(user_id, role_id, actor_id=actor.id); return {"success": True}

    @app.delete("/api/users/{user_id}/roles/{role_id}")
    async def remove_role(user_id: str, role_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "users", "update"); _require_manageable_user(hub, actor, user_id); _require_manageable_role(hub, actor, role_id); hub.remove_role(user_id, role_id, actor_id=actor.id); return {"success": True}

    @app.post("/api/roles/{role_id}/permissions/{permission_code:path}")
    async def assign_permission(role_id: str, permission_code: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "roles", "update"); _require_manageable_role(hub, actor, role_id); _require_assignable_permission(hub, actor, permission_code); hub.assign_permission(role_id, permission_code, actor_id=actor.id); return {"success": True}

    @app.delete("/api/roles/{role_id}/permissions/{permission_code:path}")
    async def remove_permission(role_id: str, permission_code: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "roles", "update"); _require_manageable_role(hub, actor, role_id); _require_assignable_permission(hub, actor, permission_code); hub.remove_permission(role_id, permission_code, actor_id=actor.id); return {"success": True}

    @app.get("/api/permissions")
    async def list_permissions(authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "permissions", "read")
        return {"items": [hub.permission_dict(item) for item in hub.list_permissions()]}

    @app.post("/api/permissions")
    async def create_permission(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "permissions", "create")
        for role_id in payload.get("role_ids") or []:
            _require_manageable_role(hub, actor, str(role_id))
        permission = hub.create_permission(payload.get("code"), str(payload.get("name", "")), description=payload.get("description"), kind=str(payload.get("kind", "operation")), module_id=payload.get("module_id"), resource_id=payload.get("resource_id"), action=payload.get("action"), scope=str(payload.get("scope") or "global"), role_ids=payload.get("role_ids") or [], metadata=payload.get("metadata"), actor_id=actor.id)
        return hub.permission_dict(permission)

    @app.patch("/api/permissions/{permission_code:path}")
    async def update_permission(permission_code: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "permissions", "update")
        _require_assignable_permission(hub, actor, permission_code)
        return hub.permission_dict(hub.update_permission(permission_code, name=payload.get("name"), description=payload.get("description"), enabled=payload.get("enabled"), metadata=payload.get("metadata"), actor_id=actor.id))

    @app.get("/api/modules")
    async def list_modules(authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "modules", "read")
        return {"items": [item.to_dict() for item in hub.list_modules()]}

    @app.get("/api/modules/{module_id}")
    async def get_module(module_id: str, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "modules", "read")
        return hub.get_module(module_id).to_dict()

    @app.get("/api/resources")
    async def list_resources(module_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "resources", "read")
        return {"items": [hub.resource_dict(item) for item in hub.list_resources(module_id)]}

    @app.post("/api/resources")
    async def create_resource(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "resources", "create")
        return hub.resource_dict(hub.create_resource(str(payload.get("module_id") or ""), str(payload.get("resource_type") or ""), str(payload.get("resource_key") or ""), str(payload.get("name") or ""), metadata=payload.get("metadata"), actor_id=actor.id))

    @app.delete("/api/resources/{resource_id}")
    async def delete_resource(resource_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "resources", "delete")
        if resource_id.startswith(f"{AUTHHUB_SYSTEM_MODULE_ID}:"):
            raise ValidationError("built-in AuthHub resources cannot be deleted")
        hub.delete_resource(resource_id, actor_id=actor.id)
        return {"success": True}

    @app.get("/api/resource-instances")
    async def list_resource_instances(resource_id: Optional[str] = None, owner_user_id: Optional[str] = None, organization_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "resource-instances", "read")
        return {"items": [{**hub.resource_instance_dict(item), "grant_count": len(hub.resource_instance_grants(item.id))} for item in hub.repository.list_resource_instances(resource_id, owner_user_id=owner_user_id, organization_id=organization_id)]}

    # Declare this static route before /{instance_id}/grants. Starlette matches
    # routes in registration order and otherwise treats "by-external" as an ID.
    @app.get("/api/resource-instances/by-external/grants")
    async def list_owned_resource_instance_grants(resource_id: str, external_id: str, authorization: Optional[str] = Header(None)):
        """Read grants for one record as its owner or a system administrator."""
        _actor, instance = _require_resource_grant_manager(hub, authorization, resource_id, external_id)
        return {"items": [_grant_with_user(hub, item) for item in hub.resource_instance_grants(instance.id)]}

    @app.put("/api/resource-instances/by-external/grants")
    async def replace_owned_resource_instance_grants(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        resource_id = str(payload.get("resource_id") or "")
        external_id = str(payload.get("external_id") or "")
        grants = payload.get("grants")
        if not resource_id or not external_id: raise ValidationError("resource_id and external_id are required")
        if not isinstance(grants, list): raise ValidationError("grants must be a list")
        actor, instance = _require_resource_grant_manager(hub, authorization, resource_id, external_id)
        _require_delegable_resource_grants(hub, actor, instance, grants)
        stored = hub.replace_resource_instance_grants(instance.id, grants, actor_id=actor.id)
        return {"items": [_grant_with_user(hub, item) for item in stored]}

    @app.get("/api/resource-instances/by-external/public-permissions")
    async def get_owned_resource_instance_public_permissions(resource_id: str, external_id: str, authorization: Optional[str] = Header(None)):
        _actor, instance = _require_resource_grant_manager(hub, authorization, resource_id, external_id)
        return _public_permission_payload(hub, instance)

    @app.put("/api/resource-instances/by-external/public-permissions")
    async def replace_owned_resource_instance_public_permissions(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        resource_id = str(payload.get("resource_id") or "")
        external_id = str(payload.get("external_id") or "")
        if not resource_id or not external_id: raise ValidationError("resource_id and external_id are required")
        actor, instance = _require_resource_grant_manager(hub, authorization, resource_id, external_id)
        permission_codes = payload.get("permission_codes")
        if permission_codes is not None and not isinstance(permission_codes, list): raise ValidationError("permission_codes must be a list or null")
        return _public_permission_payload(hub, hub.replace_resource_instance_public_permissions(instance.id, permission_codes, actor_id=actor.id))

    @app.get("/api/resource-instances/{instance_id}/grants")
    async def list_resource_instance_grants(instance_id: str, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "resource-instances", "read")
        return {"items": [hub.resource_instance_grant_dict(item) for item in hub.resource_instance_grants(instance_id)]}

    @app.put("/api/resource-instances/{instance_id}/grants")
    async def replace_resource_instance_grants(instance_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "resource-instances", "update")
        grants = payload.get("grants")
        if not isinstance(grants, list): raise ValidationError("grants must be a list")
        instance = hub.resource_instance(instance_id)
        _require_delegable_resource_grants(hub, actor, instance, grants)
        return {"items": [hub.resource_instance_grant_dict(item) for item in hub.replace_resource_instance_grants(instance_id, grants, actor_id=actor.id)]}

    @app.get("/api/resource-instances/{instance_id}/public-permissions")
    async def get_resource_instance_public_permissions(instance_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "resource-instances", "read")
        instance = hub.resource_instance(instance_id)
        return _public_permission_payload(hub, instance)

    @app.put("/api/resource-instances/{instance_id}/public-permissions")
    async def replace_resource_instance_public_permissions(instance_id: str, payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "resource-instances", "update")
        permission_codes = payload.get("permission_codes")
        if permission_codes is not None and not isinstance(permission_codes, list): raise ValidationError("permission_codes must be a list or null")
        return _public_permission_payload(hub, hub.replace_resource_instance_public_permissions(instance_id, permission_codes, actor_id=actor.id))

    @app.post("/api/resource-instances")
    async def register_resource_instance(payload: Dict[str, Any], authorization: Optional[str] = Header(None), x_auth_hub_registration_key: Optional[str] = Header(None, alias="X-AuthHub-Registration-Key")):
        actor_id = _module_registrar_actor(hub, authorization, x_auth_hub_registration_key)
        changes = {key: payload[key] for key in ("owner_user_id", "organization_id", "metadata") if key in payload}
        instance = hub.register_resource_instance(str(payload.get("resource_id") or ""), str(payload.get("external_id") or ""), actor_id=actor_id, **changes)
        return hub.resource_instance_dict(instance)

    @app.delete("/api/resource-instances")
    async def unregister_resource_instance(resource_id: str, external_id: str, authorization: Optional[str] = Header(None), x_auth_hub_registration_key: Optional[str] = Header(None, alias="X-AuthHub-Registration-Key")):
        actor_id = _module_registrar_actor(hub, authorization, x_auth_hub_registration_key)
        hub.delete_resource_instance_by_external_id(resource_id, external_id, actor_id=actor_id)
        return {"success": True, "resource_id": resource_id, "external_id": external_id}

    @app.delete("/api/resource-instances/by-id/{instance_id}")
    async def delete_resource_instance(instance_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "resource-instances", "delete")
        hub.delete_resource_instance(instance_id, actor_id=actor.id)
        return {"success": True}

    @app.delete("/api/modules/{module_id}")
    async def delete_module(module_id: str, authorization: Optional[str] = Header(None)):
        actor = _require_system_permission(hub, authorization, "entity", "modules", "delete")
        if module_id == AUTHHUB_SYSTEM_MODULE_ID:
            raise ValidationError("built-in AuthHub module cannot be deleted")
        hub.delete_module(module_id, actor_id=actor.id); return {"success": True}

    @app.get("/api/audit-events")
    async def list_audit_events(limit: int = 100, actor_id: Optional[str] = None, action: Optional[str] = None, authorization: Optional[str] = Header(None)):
        _require_system_permission(hub, authorization, "entity", "audit-events", "read")
        return {"items": [hub.audit_event_dict(event) for event in hub.list_audit_events(limit=limit, actor_id=actor_id, action=action)]}

    @app.post("/api/modules/register")
    async def register_module(payload: Dict[str, Any], authorization: Optional[str] = Header(None), x_auth_hub_registration_key: Optional[str] = Header(None, alias="X-AuthHub-Registration-Key")):
        if str(payload.get("module_id") or payload.get("moduleId") or "") == AUTHHUB_SYSTEM_MODULE_ID:
            raise ValidationError("the built-in AuthHub module is managed by framework bootstrap")
        actor_id = _module_registrar_actor(hub, authorization, x_auth_hub_registration_key)
        return hub.register_module(payload.get("module_id") or payload.get("moduleId"), str(payload.get("module_name") or payload.get("moduleName") or ""), description=payload.get("description"), permissions=payload.get("permissions"), apis=payload.get("apis"), resources=payload.get("resources"), metadata=payload.get("metadata"), actor_id=actor_id).to_dict()

    app.state.auth_hub = hub
    return app


def _require_admin(hub: AuthHub, authorization: Optional[str]):
    actor = hub.authenticate(_bearer(authorization))
    if not actor.is_super_admin:
        raise AuthorizationError("SYSTEM_ADMIN_REQUIRED")
    return actor


def _require_system_permission(hub: AuthHub, authorization: Optional[str], resource_type: str, resource_key: str, action: str):
    """Authorize an AuthHub management endpoint through built-in RBAC."""
    token = _bearer(authorization)
    actor = hub.authenticate(token)
    permission = authhub_system_permission(resource_type, resource_key, action)
    result = hub.check_permission(token, permission, context={"module": AUTHHUB_SYSTEM_MODULE_ID, "resource": resource_key})
    if not result.allowed:
        raise AuthorizationError("PERMISSION_DENIED", f"missing permission: {permission}")
    return actor


def _require_manageable_user(hub: AuthHub, actor: Any, user_id: str):
    user = hub.repository.get_user(user_id)
    if not user:
        raise NotFoundError("user", user_id)
    if user.is_super_admin and not actor.is_super_admin:
        raise AuthorizationError("PERMISSION_DENIED", "system administrators can only be managed by a system administrator")
    return user


def _require_manageable_role(hub: AuthHub, actor: Any, role_id: str):
    role = hub.repository.get_role(role_id)
    if not role:
        raise NotFoundError("role", role_id)
    if actor.is_super_admin:
        return role
    if role.built_in:
        raise AuthorizationError("PERMISSION_DENIED", "built-in roles can only be managed by a system administrator")
    actor_permissions = set(hub.user_permissions(actor.id))
    role_permissions = set(hub.repository.role_permission_codes(role.id))
    if not role_permissions.issubset(actor_permissions):
        raise AuthorizationError("PERMISSION_DENIED", "cannot manage a role with permissions you do not hold")
    return role


def _require_assignable_role(hub: AuthHub, actor: Any, role_id: str):
    return _require_manageable_role(hub, actor, role_id)


def _require_assignable_permission(hub: AuthHub, actor: Any, permission_code: str):
    permission = hub.repository.get_permission(permission_code)
    if not permission:
        raise NotFoundError("permission", permission_code)
    if not actor.is_super_admin and permission.code not in set(hub.user_permissions(actor.id)):
        raise AuthorizationError("PERMISSION_DENIED", "cannot delegate a permission you do not hold")
    return permission


def _require_delegable_resource_grants(hub: AuthHub, actor: Any, instance: Any, grants: list[Dict[str, Any]]) -> None:
    """Only new grants are delegated; unchanged grants may be retained safely."""
    if actor.is_super_admin:
        return
    existing = {
        (grant.user_id, grant.permission_code)
        for grant in hub.resource_instance_grants(instance.id)
    }
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        user_id = str(grant.get("user_id") or "")
        permission_codes = grant.get("permission_codes") or grant.get("permissions") or []
        if isinstance(permission_codes, str):
            permission_codes = [permission_codes]
        for permission_code in permission_codes:
            pair = (user_id, str(permission_code))
            if pair not in existing:
                _require_assignable_permission(hub, actor, pair[1])


def _require_resource_grant_manager(hub: AuthHub, authorization: Optional[str], resource_id: str, external_id: str):
    """Allow a system administrator or the exact record owner to manage grants."""
    actor = hub.authenticate(_bearer(authorization))
    instance = hub.repository.get_resource_instance_by_external_id(resource_id, external_id)
    if not instance:
        raise NotFoundError("resource_instance", f"{resource_id}:{external_id}")
    if actor.is_super_admin or instance.owner_user_id == actor.id:
        return actor, instance
    raise AuthorizationError("PERMISSION_DENIED", "only the resource owner may manage grants")


def _share_user_dict(user: Any) -> Dict[str, str]:
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


def _grant_with_user(hub: AuthHub, grant: Any) -> Dict[str, Any]:
    value = hub.resource_instance_grant_dict(grant)
    user = hub.repository.get_user(grant.user_id)
    if user:
        value["user"] = _share_user_dict(user)
    return value


def _public_permission_payload(hub: AuthHub, instance: Any) -> Dict[str, Any]:
    permissions = [item for item in hub.list_permissions() if item.enabled and item.metadata.get("resource_id") == instance.resource_id]
    configured = isinstance(instance.metadata.get("public_permission_codes"), (list, tuple, set))
    return {"resource_instance": hub.resource_instance_dict(instance), "configured": configured, "selected_permission_codes": hub.resource_instance_public_permission_codes(instance.id), "permissions": [hub.permission_dict(item) for item in permissions]}


def _module_registrar_actor(hub: AuthHub, authorization: Optional[str], registration_key: Optional[str]) -> str:
    configured_key = hub.settings.module_registration_key
    if configured_key and registration_key and hmac.compare_digest(configured_key, registration_key):
        return "service:module-registration"
    logger.warning(
        "module registration authentication failed configured_key=%s supplied_key=%s bearer_token=%s",
        bool(configured_key),
        bool(registration_key),
        bool(_bearer(authorization)),
    )
    return _require_admin(hub, authorization).id


def _bearer(value: Optional[str]) -> str:
    if not value or not value.lower().startswith("bearer "): return ""
    return value[7:].strip()
