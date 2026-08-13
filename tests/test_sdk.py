import os
import sys
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from auth_hub import AuthHub, AuthHubSettings
from auth_hub.api import _module_registrar_actor
from auth_hub_client import AuthHubOutbox, AuthHubOutboxDispatcher, ModuleManifest, PermissionSpec, ResourceSpec, track_resource_instance, untrack_resource_instance


class ClientSdkTests(unittest.TestCase):
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
