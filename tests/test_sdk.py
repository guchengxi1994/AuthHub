import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from auth_hub import AuthHub, AuthHubSettings
from auth_hub.api import _module_registrar_actor
from auth_hub_client import AuthHubClient, AuthHubOutbox, AuthHubOutboxDispatcher, ModuleManifest, PermissionSpec, ResourceSpec, track_resource_instance, untrack_resource_instance


class ClientSdkTests(unittest.TestCase):
    def test_client_lists_users_with_caller_token(self):
        client = AuthHubClient("http://auth-hub")
        with patch.object(client, "_request", return_value={"items": []}) as request:
            self.assertEqual(client.list_users("user-token"), {"items": []})
        request.assert_called_once_with("GET", "/api/users", headers={"Authorization": "Bearer user-token"})

        with patch.object(client, "_request", return_value={"items": []}) as request:
            client.list_users("user-token", query="张三", limit=50)
        request.assert_called_once_with("GET", "/api/users?query=%E5%BC%A0%E4%B8%89&limit=50", headers={"Authorization": "Bearer user-token"})

        with patch.object(client, "_request", return_value={"results": []}) as request:
            self.assertEqual(client.check_user_access("user-1", [{"id": "tool", "permission": "mcp:tool:execute"}]), {"results": []})
        request.assert_called_once_with(
            "POST",
            "/api/service/users/user-1/access-checks",
            {"checks": [{"id": "tool", "permission": "mcp:tool:execute"}]},
            headers={},
        )

    def test_manifest_uses_business_declared_mcp_tool_and_stable_code(self):
        manifest = ModuleManifest(
            module_id="knowledge",
            name="Knowledge service",
            resources=[ResourceSpec.mcp_tool("search", "Knowledge search")],
            permissions=[PermissionSpec("execute", "Run search", resource="search")],
        )
        payload = manifest.to_payload()
        self.assertEqual(payload["resources"][0]["resource_type"], "mcp_tool")
        self.assertEqual(payload["resources"][0]["resource_key"], "search")
        self.assertEqual(manifest.permission_code("search", "execute"), "knowledge:mcp_tool:search:execute")
        self.assertEqual(manifest.resource_id("search"), "knowledge:mcp_tool:search")
        self.assertEqual(payload["resources"][0]["id"], "knowledge:mcp_tool:search")
        self.assertEqual(payload["permissions"][0]["resource_id"], "knowledge:mcp_tool:search")

    def test_manifest_registration_resolves_resources_and_permissions(self):
        hub = AuthHub.in_memory()
        manifest = ModuleManifest(
            module_id="knowledge",
            name="Knowledge service",
            resources=[ResourceSpec.mcp_tool("search", "Knowledge search")],
            permissions=[PermissionSpec("execute", "Run search", resource="search")],
        )
        module = hub.register_module(**manifest.to_payload())
        permission = hub.repository.get_permission("knowledge:mcp_tool:search:execute")
        self.assertEqual(module.id, "knowledge")
        self.assertIsNotNone(permission)
        self.assertEqual(permission.metadata["resource_type"], "mcp_tool")
        self.assertEqual(permission.metadata["resource_key"], "search")
        self.assertTrue(permission.metadata["resource_id"])

    def test_manifest_resource_id_requires_declared_module_and_resource(self):
        manifest = ModuleManifest(name="No ID", resources=[ResourceSpec.entity("order", "Order")])
        with self.assertRaises(ValueError):
            manifest.resource_id("order")
        manifest = ModuleManifest(module_id="orders", name="Orders", resources=[])
        with self.assertRaises(ValueError):
            manifest.resource_id("order")

    def test_registration_key_allows_service_sync_without_admin_token(self):
        hub = AuthHub.in_memory(AuthHubSettings(module_registration_key="test-registration-key"))
        self.assertEqual(_module_registrar_actor(hub, None, "test-registration-key"), "service:module-registration")
        with self.assertRaises(Exception):
            _module_registrar_actor(hub, None, "wrong-key")

    def test_registration_endpoint_accepts_sdk_header_name(self):
        from auth_hub.api import create_app

        app = create_app(auth_hub=AuthHub.in_memory(AuthHubSettings(module_registration_key="test-registration-key")))
        with TestClient(app) as client:
            response = client.post(
                "/api/modules/register",
                headers={"X-AuthHub-Registration-Key": "test-registration-key"},
                json={"module_id": "sdk-probe", "module_name": "SDK probe", "resources": [], "permissions": []},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "sdk-probe")

    def test_registration_endpoint_cannot_overwrite_builtin_authhub_module(self):
        from auth_hub.api import create_app

        with TestClient(create_app(auth_hub=AuthHub.in_memory(AuthHubSettings(module_registration_key="test-registration-key")))) as client:
            response = client.post(
                "/api/modules/register",
                headers={"X-AuthHub-Registration-Key": "test-registration-key"},
                json={"module_id": "authhub", "module_name": "Overridden", "resources": [], "permissions": []},
            )

        self.assertEqual(response.status_code, 422)

    def test_runtime_metadata_reports_running_release(self):
        from auth_hub.api import create_app

        with patch.dict(os.environ, {"AUTH_HUB_RELEASE": "2.3.4", "AUTH_HUB_BUILD": "test-build"}):
            with TestClient(create_app(auth_hub=AuthHub.in_memory())) as client:
                response = client.get("/api/meta")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"version": "2.3.4", "build": "test-build"})

    def test_builtin_management_endpoints_use_assignable_permissions(self):
        from auth_hub.api import create_app

        hub = AuthHub.in_memory()
        organization = hub.create_organization("Engineering")
        role = hub.create_role("support-reader", "Support reader")
        user = hub.create_user("support", "password", role_ids=[role.id])
        hub.assign_permission(role.id, "authhub:entity:users:read")
        app = create_app(auth_hub=hub)

        with TestClient(app) as client:
            token = client.post("/api/auth/login", json={"username": "support", "password": "password"}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            self.assertEqual(client.get("/api/users", headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/organizations", headers=headers).status_code, 403)
            self.assertEqual(client.get(f"/api/roles/{role.id}/permissions", headers=headers).status_code, 403)
            self.assertEqual(client.get("/api/auth/users/resolve", params={"username": "admin"}, headers=headers).status_code, 403)

            hub.assign_permission(role.id, "authhub:entity:organizations:read")
            hub.assign_permission(role.id, "authhub:entity:roles:read")
            hub.assign_permission(role.id, "authhub:custom:share-recipient:read")
            self.assertEqual(client.get("/api/organizations", headers=headers).status_code, 200)
            self.assertEqual(client.get(f"/api/roles/{role.id}/permissions", headers=headers).status_code, 200)
            resolved = client.get("/api/auth/users/resolve", params={"username": "admin"}, headers=headers)
            self.assertEqual(resolved.status_code, 200)
            self.assertEqual(resolved.json()["username"], "admin")

    def test_management_permissions_cannot_be_used_to_escalate_roles(self):
        from auth_hub.api import create_app

        hub = AuthHub.in_memory()
        operator_role = hub.create_role("user-editor", "User editor")
        hub.assign_permission(operator_role.id, "authhub:entity:users:update")
        operator = hub.create_user("operator", "password", role_ids=[operator_role.id])
        protected_role = hub.create_role("protected", "Protected")
        hub.assign_permission(protected_role.id, "authhub:entity:users:delete")
        app = create_app(auth_hub=hub)

        with TestClient(app) as client:
            token = client.post("/api/auth/login", json={"username": "operator", "password": "password"}).json()["access_token"]
            response = client.post(
                f"/api/users/{operator.id}/roles/{protected_role.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 403)

    def test_resource_instance_grant_management_api_and_resource_check(self):
        from auth_hub.api import create_app

        hub = AuthHub.in_memory()
        module = hub.register_module("mcp", "MCP")
        resource = hub.create_resource(module.id, "mcp_server", "server", "MCP servers")
        permission = hub.create_permission(None, "Manage server", module_id=module.id, resource_id=resource.id, action="manage")
        collaborator = hub.create_user("collaborator", "password")
        instance = hub.register_resource_instance(resource.id, "server-100")
        app = create_app(auth_hub=hub)

        with TestClient(app) as client:
            admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "change-me-now"}).json()["access_token"]
            headers = {"Authorization": f"Bearer {admin_token}"}
            response = client.put(f"/api/resource-instances/{instance.id}/grants", headers=headers, json={"grants": [{"user_id": collaborator.id, "permission_codes": [permission.code]}]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["items"]), 1)
            index = client.get("/api/resource-instances", headers=headers).json()["items"]
            self.assertEqual(index[0]["grant_count"], 1)
            token = client.post("/api/auth/login", json={"username": "collaborator", "password": "password"}).json()["access_token"]
            result = client.post("/api/auth/check-resource", headers={"Authorization": f"Bearer {token}"}, json={"permission": permission.code, "resource_id": resource.id, "external_id": "server-100"}).json()
            self.assertTrue(result["allowed"])
            self.assertEqual(result["matched_by"], "resource_grant")

    def test_service_access_check_evaluates_a_recipient_without_their_token(self):
        from auth_hub.api import create_app

        hub = AuthHub.in_memory(AuthHubSettings(module_registration_key="service-key"))
        module = hub.register_module("mcp", "MCP")
        resource = hub.create_resource(module.id, "mcp_tool", "tool", "MCP tools")
        permission = hub.create_permission(None, "Execute tool", module_id=module.id, resource_id=resource.id, action="execute")
        recipient = hub.create_user("recipient", "password")
        instance = hub.register_resource_instance(resource.id, "orders:query")
        app = create_app(auth_hub=hub)

        payload = {"checks": [{"id": "orders-query", "permission": permission.code, "resource_id": resource.id, "external_id": instance.external_id}]}
        with TestClient(app) as client:
            headers = {"X-AuthHub-Registration-Key": "service-key"}
            denied = client.post(f"/api/service/users/{recipient.id}/access-checks", headers=headers, json=payload)
            self.assertEqual(denied.status_code, 200)
            self.assertFalse(denied.json()["results"][0]["allowed"])

            hub.replace_resource_instance_grants(instance.id, [{"user_id": recipient.id, "permission_codes": [permission.code]}])
            allowed = client.post(f"/api/service/users/{recipient.id}/access-checks", headers=headers, json=payload)
            self.assertEqual(allowed.status_code, 200)
            self.assertTrue(allowed.json()["results"][0]["allowed"])
            self.assertEqual(allowed.json()["results"][0]["matched_by"], "resource_grant")

    def test_resource_owner_can_share_by_external_id_without_admin_access(self):
        from auth_hub.api import create_app

        hub = AuthHub.in_memory()
        module = hub.register_module("skills", "Skills")
        resource = hub.create_resource(module.id, "custom", "skill", "MCP Skill")
        permission = hub.create_permission(None, "Execute Skill", module_id=module.id, resource_id=resource.id, action="execute", scope="owner")
        owner = hub.create_user("skill-owner", "password")
        recipient = hub.create_user("skill-user", "password")
        share_role = hub.create_role("skill-sharing", "Skill sharing")
        hub.assign_permission(share_role.id, "authhub:custom:share-recipient:read")
        hub.assign_role(owner.id, share_role.id)
        hub.register_resource_instance(resource.id, "customer-summary", owner_user_id=owner.id)
        app = create_app(auth_hub=hub)

        with TestClient(app) as client:
            owner_token = client.post("/api/auth/login", json={"username": "skill-owner", "password": "password"}).json()["access_token"]
            headers = {"Authorization": f"Bearer {owner_token}"}
            resolved = client.get("/api/auth/users/resolve", params={"username": "skill-user"}, headers=headers)
            self.assertEqual(resolved.status_code, 200)
            self.assertEqual(resolved.json()["id"], recipient.id)
            denied_grant = client.put(
                "/api/resource-instances/by-external/grants",
                headers=headers,
                json={"resource_id": resource.id, "external_id": "customer-summary", "grants": [{"user_id": recipient.id, "permission_codes": [permission.code]}]},
            )
            self.assertEqual(denied_grant.status_code, 403)
            hub.assign_permission(share_role.id, permission.code)
            response = client.put(
                "/api/resource-instances/by-external/grants",
                headers=headers,
                json={"resource_id": resource.id, "external_id": "customer-summary", "grants": [{"user_id": recipient.id, "permission_codes": [permission.code]}]},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["user"]["username"], "skill-user")
            recipient_token = client.post("/api/auth/login", json={"username": "skill-user", "password": "password"}).json()["access_token"]
            denied = client.get(
                "/api/resource-instances/by-external/grants",
                params={"resource_id": resource.id, "external_id": "customer-summary"},
                headers={"Authorization": f"Bearer {recipient_token}"},
            )
            self.assertEqual(denied.status_code, 403)
            result = client.post("/api/auth/check-resource", headers={"Authorization": f"Bearer {recipient_token}"}, json={"permission": permission.code, "resource_id": resource.id, "external_id": "customer-summary"}).json()
            self.assertTrue(result["allowed"])
            self.assertEqual(result["matched_by"], "resource_grant")

    def test_sqlalchemy_outbox_decorator_is_transactional_and_dispatches_idempotently(self):
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from sqlalchemy import MetaData, Table, Column, Integer, String

        metadata = MetaData()
        orders = Table("orders", metadata, Column("id", Integer, primary_key=True), Column("owner_id", String(64)))
        outbox = AuthHubOutbox(metadata)
        engine = create_engine("sqlite+pysqlite:///:memory:")
        metadata.create_all(engine)

        class FakeClient:
            def __init__(self): self.calls = []
            def register_resource_instance(self, *args, **kwargs): self.calls.append(("upsert", args, kwargs)); return {}
            def unregister_resource_instance(self, *args, **kwargs): self.calls.append(("delete", args, kwargs)); return {}

        fake = FakeClient()
        dispatcher = AuthHubOutboxDispatcher(outbox, fake, base_retry_seconds=1)

        @track_resource_instance(outbox, resource_id="orders:entity:order", external_id=lambda row: row.id, owner_user_id=lambda row: row.owner_id)
        def create_order(*, session):
            result = session.execute(orders.insert().values(owner_id="user-1"))
            return session.execute(select(orders).where(orders.c.id == result.inserted_primary_key[0])).mappings().one()

        with Session(engine) as session:
            create_order(session=session)
            self.assertEqual(session.execute(select(outbox.table)).fetchall().__len__(), 1)
            session.commit()
            self.assertEqual(len(fake.calls), 0)
            result = dispatcher.dispatch(session)
            self.assertEqual(result.delivered, 1)
            session.commit()
            self.assertEqual(len(fake.calls), 1)

        with Session(engine) as session:
            @untrack_resource_instance(outbox, resource_id="orders:entity:order", external_id=lambda row: row.id)
            def delete_order(*, session):
                row = session.execute(select(orders)).mappings().first()
                session.execute(orders.delete())
                return row
            delete_order(session=session)
            session.commit()
            result = dispatcher.dispatch(session)
            self.assertEqual(result.delivered, 1)
            session.commit()
            self.assertEqual([call[0] for call in fake.calls], ["upsert", "delete"])

        with Session(engine) as session:
            @track_resource_instance(outbox, resource_id="orders:entity:order", external_id=lambda row: row.id)
            def rolled_back(*, session):
                result = session.execute(orders.insert().values(owner_id="user-2"))
                row = session.execute(select(orders).where(orders.c.id == result.inserted_primary_key[0])).mappings().one()
                raise RuntimeError("business failure")
            with self.assertRaises(RuntimeError):
                rolled_back(session=session)
            session.rollback()
            pending = session.execute(select(outbox.table).where(outbox.table.c.delivered_at.is_(None))).fetchall()
            self.assertEqual(len(pending), 0)

    def test_sqlalchemy_outbox_defers_failures_and_preserves_event_order(self):
        from sqlalchemy import MetaData, create_engine, select
        from sqlalchemy.orm import Session

        metadata = MetaData()
        outbox = AuthHubOutbox(metadata)
        engine = create_engine("sqlite+pysqlite:///:memory:")
        metadata.create_all(engine)

        class FailingClient:
            def register_resource_instance(self, *args, **kwargs): raise RuntimeError("AuthHub offline")
            def unregister_resource_instance(self, *args, **kwargs): raise RuntimeError("AuthHub offline")

        dispatcher = AuthHubOutboxDispatcher(outbox, FailingClient(), base_retry_seconds=1, max_attempts=2)
        with Session(engine) as session:
            outbox.enqueue_upsert(session, "orders:entity:order", "order-100", owner_user_id="user-1")
            outbox.enqueue_delete(session, "orders:entity:order", "order-100")
            session.commit()
            result = dispatcher.dispatch(session)
            self.assertEqual((result.delivered, result.deferred, result.dead), (0, 1, 0))
            session.commit()
            rows = session.execute(select(outbox.table).order_by(outbox.table.c.sequence)).mappings().all()
            self.assertEqual(rows[0]["attempts"], 1)
            self.assertIsNotNone(rows[0]["last_error"])
            self.assertEqual(rows[1]["attempts"], 0)
            session.execute(outbox.table.update().where(outbox.table.c.event_id == rows[0]["event_id"]).values(available_at=rows[0]["available_at"] - timedelta(seconds=2)))
            session.commit()
            result = dispatcher.dispatch(session)
            self.assertEqual((result.delivered, result.deferred, result.dead), (0, 0, 1))
            session.commit()
            first = session.execute(select(outbox.table).order_by(outbox.table.c.sequence)).mappings().first()
            self.assertIsNotNone(first["dead_at"])


if __name__ == "__main__":
    unittest.main()
