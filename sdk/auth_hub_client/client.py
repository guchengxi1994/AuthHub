from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_UNSET = object()


class AuthHubClientError(RuntimeError):
    def __init__(self, message: str, *, code: Optional[str] = None, status_code: Optional[int] = None, details: Any = None) -> None:
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details


class AuthorizationDenied(AuthHubClientError):
    def __init__(self, permission: str, reason: str = "PERMISSION_DENIED") -> None:
        super().__init__(f"permission denied: {permission}", code=reason, status_code=403)
        self.permission = permission


@dataclass(frozen=True)
class ResourceSpec:
    key: str
    name: str
    resource_type: str = "api"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    id: Optional[str] = None

    @classmethod
    def api(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "api", **kwargs)
    @classmethod
    def entity(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "entity", **kwargs)
    @classmethod
    def mcp_server(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "mcp_server", **kwargs)
    @classmethod
    def mcp_tool(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "mcp_tool", **kwargs)
    @classmethod
    def page(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "page", **kwargs)
    @classmethod
    def ui_action(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "ui_action", **kwargs)
    @classmethod
    def ui_component(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "ui_component", **kwargs)
    @classmethod
    def custom(cls, key: str, name: str, **kwargs: Any) -> "ResourceSpec": return cls(key, name, "custom", **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"resource_type": self.resource_type, "resource_key": self.key, "name": self.name}
        if self.id: result["id"] = self.id
        if self.metadata: result["metadata"] = dict(self.metadata)
        return result

    def resolved_id(self, module_id: str) -> str:
        """Return the deterministic AuthHub resource definition ID."""
        return self.id or f"{module_id}:{self.resource_type}:{self.key}"


@dataclass(frozen=True)
class PermissionSpec:
    action: str
    name: str
    resource: str
    code: Optional[str] = None
    description: Optional[str] = None
    id: Optional[str] = None
    scope: str = "global"

    def resolved_code(self, module_id: str, resources: Mapping[str, ResourceSpec]) -> str:
        resource = resources.get(self.resource)
        if not resource: raise ValueError(f"permission references unknown resource: {self.resource}")
        return self.id or self.code or f"{module_id}:{resource.resource_type}:{resource.key}:{self.action}"

    def to_dict(self, resources: Mapping[str, ResourceSpec]) -> Dict[str, Any]:
        resource = resources.get(self.resource)
        if not resource: raise ValueError(f"permission references unknown resource: {self.resource}")
        result: Dict[str, Any] = {"id": self.id or self.code or "", "name": self.name, "resource_id": resource.id or "", "resource_type": resource.resource_type, "resource_key": resource.key, "action": self.action, "scope": self.scope}
        if self.description: result["description"] = self.description
        return result


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    resources: Sequence[ResourceSpec]
    permissions: Sequence[PermissionSpec] = field(default_factory=tuple)
    module_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def permission_code(self, resource_key: str, action: str) -> str:
        if not self.module_id: raise ValueError("module_id is required to derive a stable permission code")
        resources = {item.key: item for item in self.resources}
        permission = next((item for item in self.permissions if item.resource == resource_key and item.action == action), None)
        if not permission: raise ValueError(f"no declared permission for {resource_key}:{action}")
        return permission.resolved_code(self.module_id, resources)

    def resource_id(self, resource_key: str) -> str:
        """Return the stable resource ID used by object-level checks."""
        if not self.module_id: raise ValueError("module_id is required to derive a stable resource ID")
        resource = next((item for item in self.resources if item.key == resource_key), None)
        if not resource: raise ValueError(f"unknown resource: {resource_key}")
        return resource.resolved_id(self.module_id)

    def to_payload(self) -> Dict[str, Any]:
        resources = {item.key: item for item in self.resources}
        if len(resources) != len(self.resources): raise ValueError("resource keys must be unique within a module")
        missing = [item.resource for item in self.permissions if item.resource not in resources]
        if missing: raise ValueError(f"permissions reference unknown resources: {', '.join(missing)}")
        resource_payloads = []
        for item in self.resources:
            payload = item.to_dict()
            if self.module_id:
                payload["id"] = item.resolved_id(self.module_id)
            resource_payloads.append(payload)
        permissions = []
        for item in self.permissions:
            payload = item.to_dict(resources)
            if self.module_id:
                payload["resource_id"] = self.resource_id(item.resource)
            permissions.append(payload)
        return {"module_id": self.module_id, "module_name": self.name, "description": self.description, "metadata": dict(self.metadata), "resources": resource_payloads, "permissions": permissions, "apis": []}


class AuthHubClient:
    """HTTP client used by business backends, not browser code."""

    def __init__(self, base_url: str, *, registration_key: Optional[str] = None, timeout: float = 5.0) -> None:
        self.base_url, self.registration_key, self.timeout = base_url.rstrip("/"), registration_key, timeout

    def register_module(self, manifest: ModuleManifest) -> Mapping[str, Any]:
        headers = {"X-AuthHub-Registration-Key": self.registration_key} if self.registration_key else {}
        return self._request("POST", "/api/modules/register", manifest.to_payload(), headers=headers)

    def login(self, username: str, password: str) -> Mapping[str, Any]:
        return self._request("POST", "/api/auth/login", {"username": username, "password": password})

    def refresh(self, refresh_token: str) -> Mapping[str, Any]:
        return self._request("POST", "/api/auth/refresh", {"refresh_token": refresh_token})

    def logout(self, access_token: str) -> Mapping[str, Any]:
        return self._request("POST", "/api/auth/logout", headers={"Authorization": f"Bearer {access_token}"})

    def me(self, access_token: str) -> Mapping[str, Any]:
        return self._request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    def check_token(self, access_token: str) -> Mapping[str, Any]:
        return self._request("POST", "/api/auth/check-token", headers={"Authorization": f"Bearer {access_token}"})

    def check(self, access_token: str, permission: str, *, resource: Optional[str] = None, context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        payload: Dict[str, Any] = {"permission": permission}
        if resource is not None: payload["resource"] = resource
        if context is not None: payload["context"] = dict(context)
        return self._request("POST", "/api/auth/check", payload, headers={"Authorization": f"Bearer {access_token}"})

    def check_or_raise(self, access_token: str, permission: str, *, resource: Optional[str] = None, context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        result = self.check(access_token, permission, resource=resource, context=context)
        if not result.get("authenticated"): raise AuthHubClientError("authentication required", code=result.get("reason"), status_code=401)
        if not result.get("allowed"): raise AuthorizationDenied(permission, result.get("reason", "PERMISSION_DENIED"))
        return result

    def check_resource_or_raise(self, access_token: str, permission: str, resource_id: str, external_id: str, *, context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        payload: Dict[str, Any] = {"permission": permission, "resource_id": resource_id, "external_id": external_id}
        if context is not None: payload["context"] = dict(context)
        result = self._request("POST", "/api/auth/check-resource", payload, headers={"Authorization": f"Bearer {access_token}"})
        if not result.get("authenticated"): raise AuthHubClientError("authentication required", code=result.get("reason"), status_code=401)
        if not result.get("allowed"): raise AuthorizationDenied(permission, result.get("reason", "PERMISSION_DENIED"))
        return result

    def user_permissions(self, access_token: str) -> Mapping[str, Any]:
        return self._request("GET", "/api/auth/user-permissions", headers={"Authorization": f"Bearer {access_token}"})

    def register_resource_instance(self, resource_id: str, external_id: str, *, owner_user_id: Any = _UNSET, organization_id: Any = _UNSET, metadata: Any = _UNSET) -> Mapping[str, Any]:
        payload: Dict[str, Any] = {"resource_id": resource_id, "external_id": external_id}
        if owner_user_id is not _UNSET: payload["owner_user_id"] = owner_user_id
        if organization_id is not _UNSET: payload["organization_id"] = organization_id
        if metadata is not _UNSET: payload["metadata"] = dict(metadata or {})
        headers = {"X-AuthHub-Registration-Key": self.registration_key} if self.registration_key else {}
        return self._request("POST", "/api/resource-instances", payload, headers=headers)

    def unregister_resource_instance(self, resource_id: str, external_id: str) -> Mapping[str, Any]:
        """Remove the ownership index after the business record is deleted."""
        headers = {"X-AuthHub-Registration-Key": self.registration_key} if self.registration_key else {}
        path = f"/api/resource-instances?{urlencode({'resource_id': resource_id, 'external_id': external_id})}"
        return self._request("DELETE", path, headers=headers)

    def _request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None, *, headers: Optional[Mapping[str, str]] = None) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(f"{self.base_url}{path}", data=body, headers={"Content-Type": "application/json", **dict(headers or {})}, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response: return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = json.loads(error.read().decode("utf-8")) if error.fp else {}
            raise AuthHubClientError(details.get("message", error.reason), code=details.get("code"), status_code=error.code, details=details.get("details")) from error
        except URLError as error:
            raise AuthHubClientError(f"AuthHub request failed: {error.reason}") from error
