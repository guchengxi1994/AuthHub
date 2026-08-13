import os
import tempfile
import unittest

from auth_hub import AuthHub, AuthHubSettings, InMemoryAuthHubRepository, InMemoryAuditLog, InMemoryCache, RedisCache, SQLAlchemyAuthHubRepository
from auth_hub.domain.errors import AuthenticationError, ValidationError
from auth_hub.infrastructure import CacheTokenService, InMemoryTokenService, SimplePasswordHasher
from auth_hub.domain.models import Permission, Role, User, new_id


class FrameworkTests(unittest.TestCase):
    def test_bootstrap_login_and_rbac_decision(self):
        hub = AuthHub.in_memory(AuthHubSettings(admin_password="safe-password"))
        hub.register_module("system", "System", permissions=[{"id": "system:read"}])
        tokens = hub.login("admin", "safe-password")
        self.assertTrue(tokens["access_token"])
        allowed = hub.check_permission(tokens["access_token"], "system:read")
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.matched_by, "system_admin")

    def test_role_permission_and_cache_invalidation(self):
        repository = InMemoryAuthHubRepository()
        hub = AuthHub(repository, InMemoryCache(), InMemoryTokenService(), SimplePasswordHasher(), InMemoryAuditLog())
        user = repository.save_user(User(new_id(), "alice", hub.passwords.hash("password")))
        role = repository.save_role(Role(new_id(), "reader", "Reader"))
        repository.save_permission(Permission(new_id(), "dataset:read", "Read datasets"))
        hub.assign_role(user.id, role.id)
        access = hub.tokens.issue(user)["access_token"]
        self.assertFalse(hub.check_permission(access, "dataset:read").allowed)
        hub.assign_permission(role.id, "dataset:read")
        self.assertTrue(hub.check_permission(access, "dataset:read").allowed)

    def test_disabled_user_cannot_authenticate(self):
        hub = AuthHub.in_memory(AuthHubSettings(admin_password="safe-password"))
        admin = hub.repository.get_user_by_username("admin")
        hub.repository.save_user(admin.with_changes(enabled=False))
        with self.assertRaises(AuthenticationError) as caught:
            hub.login("admin", "safe-password")
        self.assertEqual(caught.exception.code, "USER_DISABLED")

    def test_management_use_cases(self):
        hub = AuthHub.in_memory()
        user = hub.create_user("alice", "password", display_name="Alice")
        organization = hub.create_organization("Engineering")
        hub.assign_organization(user.id, organization.id)
        role = hub.create_role("reader", "Reader")
        hub.assign_role(user.id, role.id)
        self.assertEqual(hub.organization_tree()[0]["name"], "Engineering")
        self.assertEqual(hub.list_users()[1].username, "alice")

    def test_user_creation_assigns_organizations_and_roles(self):
        hub = AuthHub.in_memory()
        organization = hub.create_organization("Engineering")
        role = hub.create_role(None, "Reader")
        user = hub.create_user("alice", "password", organization_ids=[organization.id], role_ids=[role.id])
        self.assertEqual(hub.repository.user_organization_ids(user.id), {organization.id})
        self.assertEqual(hub.repository.user_role_ids(user.id), {role.id})

    def test_resource_permission_model_requires_module_resource_action_and_role_binding(self):
        hub = AuthHub.in_memory()
        module = hub.register_module(None, "Orders")
        other_module = hub.register_module(None, "Billing")
        resource = hub.create_resource(module.id, "entity", "order", "Orders")
        role = hub.create_role(None, "Order reader")
        user = hub.create_user("alice", "password", role_ids=[role.id])

        with self.assertRaises(ValidationError):
            hub.create_resource(module.id, "component", "order-list", "Order list")
        with self.assertRaises(ValidationError):
            hub.create_permission(None, "Read orders", module_id=other_module.id, resource_id=resource.id, action="read")
        with self.assertRaises(ValidationError):
            hub.create_permission(None, "Read orders", module_id=module.id, resource_id=resource.id)
        with self.assertRaises(ValidationError):
            hub.create_permission(None, "Execute orders", module_id=module.id, resource_id=resource.id, action="execute")

        action_resource = hub.create_resource(module.id, "ui_action", "order-create", "Create order")
        component_resource = hub.create_resource(module.id, "ui_component", "order-sensitive-tab", "Sensitive tab")
        action_permission = hub.create_permission(None, "Create order", module_id=module.id, resource_id=action_resource.id, action="execute", role_ids=[role.id])
        component_permission = hub.create_permission(None, "View sensitive tab", module_id=module.id, resource_id=component_resource.id, action="view", role_ids=[role.id])
        self.assertEqual(action_permission.metadata["resource_type"], "ui_action")
        self.assertEqual(component_permission.metadata["resource_type"], "ui_component")
        with self.assertRaises(ValidationError):
            hub.create_permission(None, "View create order", module_id=module.id, resource_id=action_resource.id, action="view")
        with self.assertRaises(ValidationError):
            hub.create_permission(None, "Execute sensitive tab", module_id=module.id, resource_id=component_resource.id, action="execute")

        permission = hub.create_permission(None, "Read orders", module_id=module.id, resource_id=resource.id, action="read", role_ids=[role.id])
        self.assertEqual(permission.metadata["resource_id"], resource.id)
        self.assertEqual(permission.metadata["action"], "read")
        self.assertIn(permission.code, hub.repository.role_permission_codes(role.id))
        tokens = hub.login("alice", "password")
        self.assertTrue(hub.check_permission(tokens["access_token"], permission.code).allowed)

        with self.assertRaises(ValidationError):
            hub.delete_resource(resource.id)

    def test_super_admin_permission_snapshot_contains_all_enabled_permissions(self):
        hub = AuthHub.in_memory()
        hub.register_module("orders", "Orders", permissions=[{"id": "orders:page:list:view"}])
        tokens = hub.login("admin", "change-me-now")
        self.assertIn("orders:page:list:view", hub.user_permissions(hub.authenticate(tokens["access_token"]).id))

    def test_resource_instance_owner_scope_and_super_admin_override(self):
        hub = AuthHub.in_memory()
        module = hub.register_module("orders", "Orders")
        resource = hub.create_resource(module.id, "entity", "order", "Orders")
        role = hub.create_role("order-owner", "Order owner")
        permission = hub.create_permission(None, "Update own order", module_id=module.id, resource_id=resource.id, action="update", scope="owner", role_ids=[role.id])
        alice = hub.create_user("alice", "password", role_ids=[role.id])
        bob = hub.create_user("bob", "password", role_ids=[role.id])
        instance = hub.register_resource_instance(resource.id, "order-100", owner_user_id=alice.id)
        alice_token = hub.login("alice", "password")["access_token"]
        bob_token = hub.login("bob", "password")["access_token"]
        admin_token = hub.login("admin", "change-me-now")["access_token"]
        self.assertTrue(hub.can_access_resource_instance(alice_token, permission.code, instance.id).allowed)
        self.assertEqual(hub.can_access_resource_instance(bob_token, permission.code, instance.id).reason, "RESOURCE_OWNERSHIP_DENIED")
        self.assertTrue(hub.can_access_resource_instance(admin_token, permission.code, instance.id).allowed)

    def test_resource_instance_registration_is_idempotent_and_delete_is_safe(self):
        hub = AuthHub.in_memory()
        module = hub.register_module("orders", "Orders")
        resource = hub.create_resource(module.id, "entity", "order", "Orders")
        owner = hub.create_user("owner", "password")
        instance = hub.register_resource_instance(resource.id, "order-100", owner_user_id=owner.id, metadata={"source": "orders"})
        updated = hub.register_resource_instance(resource.id, "order-100", organization_id=None)
        self.assertEqual(updated.id, instance.id)
        self.assertEqual(updated.owner_user_id, owner.id)
        self.assertEqual(updated.metadata, {"source": "orders"})
        hub.delete_resource_instance_by_external_id(resource.id, "order-100")
        hub.delete_resource_instance_by_external_id(resource.id, "order-100")
        self.assertIsNone(hub.repository.get_resource_instance_by_external_id(resource.id, "order-100"))

    def test_resource_and_module_delete_reject_existing_instance_indexes(self):
        hub = AuthHub.in_memory()
        module = hub.register_module("orders", "Orders")
        resource = hub.create_resource(module.id, "entity", "order", "Orders")
        hub.register_resource_instance(resource.id, "order-100")
        with self.assertRaises(ValidationError):
            hub.delete_resource(resource.id)
        with self.assertRaises(ValidationError):
            hub.delete_module(module.id)

    def test_resource_instance_organization_scope(self):
        hub = AuthHub.in_memory()
        module = hub.register_module("datasets", "Datasets")
        resource = hub.create_resource(module.id, "entity", "dataset", "Datasets")
        engineering = hub.create_organization("Engineering")
        sales = hub.create_organization("Sales")
        role = hub.create_role("dataset-org-reader", "Dataset organization reader")
        permission = hub.create_permission(None, "Read organization dataset", module_id=module.id, resource_id=resource.id, action="read", scope="organization", role_ids=[role.id])
        hub.create_user("engineer", "password", organization_ids=[engineering.id], role_ids=[role.id])
        hub.create_user("seller", "password", organization_ids=[sales.id], role_ids=[role.id])
        instance = hub.register_resource_instance(resource.id, "dataset-100", organization_id=engineering.id)
        engineer_token = hub.login("engineer", "password")["access_token"]
        seller_token = hub.login("seller", "password")["access_token"]
        self.assertTrue(hub.can_access_resource_instance(engineer_token, permission.code, instance.id).allowed)
        self.assertEqual(hub.can_access_resource_instance(seller_token, permission.code, instance.id).reason, "RESOURCE_ORGANIZATION_DENIED")

    def test_module_sync_cannot_remove_a_resource_referenced_by_a_permission(self):
        hub = AuthHub.in_memory()
        hub.register_module("orders", "Orders", resources=[{"resource_type": "entity", "resource_key": "order", "name": "Orders"}])
        resource = hub.list_resources("orders")[0]
        hub.create_permission(None, "Read orders", module_id="orders", resource_id=resource.id, action="read")
        with self.assertRaises(ValidationError):
            hub.register_module("orders", "Orders", resources=[])

    def test_deleting_module_removes_manual_resource_permissions_and_resources(self):
        hub = AuthHub.in_memory()
        module = hub.register_module(None, "Orders")
        resource = hub.create_resource(module.id, "api", "/orders", "Order API")
        permission = hub.create_permission(None, "Read orders", module_id=module.id, resource_id=resource.id, action="read")
        hub.delete_module(module.id)
        self.assertIsNone(hub.repository.get_module(module.id))
        self.assertEqual(hub.list_resources(module.id), [])
        self.assertIsNone(hub.repository.get_permission(permission.code))

    def test_sqlalchemy_sqlite_persists_framework_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "authhub.sqlite3")
            first = AuthHub.local(path, AuthHubSettings(admin_password="local-password"))
            self.assertIsInstance(first.repository, SQLAlchemyAuthHubRepository)
            first.create_user("persistent", "password")
            second = AuthHub.local(path, AuthHubSettings(admin_password="local-password"))
            self.assertIsNotNone(second.repository.get_user_by_username("persistent"))

    def test_sqlalchemy_persists_resource_instance_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "authhub.sqlite3")
            first = AuthHub.local(path)
            module = first.register_module("orders", "Orders")
            resource = first.create_resource(module.id, "entity", "order", "Orders")
            owner = first.create_user("owner", "password")
            instance = first.register_resource_instance(resource.id, "order-100", owner_user_id=owner.id)
            second = AuthHub.local(path)
            restored = second.repository.get_resource_instance_by_external_id(resource.id, "order-100")
            self.assertEqual(restored.id, instance.id)
            self.assertEqual(restored.owner_user_id, owner.id)

    def test_redis_cache_uses_host_supplied_client_and_namespace(self):
        class FakeRedis:
            def __init__(self): self.values = {}
            def get(self, key): return self.values.get(key)
            def setex(self, key, ttl, value): self.values[key] = value
            def delete(self, *keys):
                for key in keys: self.values.pop(key, None)
            def scan_iter(self, match):
                prefix = match[:-1]
                return [key for key in self.values if key.startswith(prefix)]

        client = FakeRedis()
        cache = RedisCache(client, namespace="service:authhub:")
        cache.set("permissions:user-1", ["dataset:read"], 60)
        self.assertEqual(cache.get("permissions:user-1"), ["dataset:read"])
        self.assertIn("service:authhub:permissions:user-1", client.values)
        cache.delete_prefix("permissions:")
        self.assertIsNone(cache.get("permissions:user-1"))

    def test_local_session_and_audit_persist_across_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "authhub.sqlite3")
            first = AuthHub.local(path, AuthHubSettings(admin_password="local-password"))
            tokens = first.login("admin", "local-password")
            self.assertTrue(first.check_permission(tokens["access_token"], "not-registered").authenticated)
            second = AuthHub.local(path, AuthHubSettings(admin_password="local-password"))
            self.assertEqual(second.authenticate(tokens["access_token"]).username, "admin")
            self.assertTrue(any(event.action == "login" for event in second.list_audit_events()))

    def test_refresh_rotation_and_disabled_user_revoke_all_sessions(self):
        hub = AuthHub.in_memory()
        user = hub.create_user("alice", "password")
        tokens = hub.login("alice", "password")
        refreshed = hub.refresh(tokens["refresh_token"])
        with self.assertRaises(AuthenticationError):
            hub.refresh(tokens["refresh_token"])
        hub.disable_user(user.id)
        with self.assertRaises(AuthenticationError) as caught:
            hub.authenticate(refreshed["access_token"])
        self.assertEqual(caught.exception.code, "TOKEN_INVALID")

    def test_cache_token_user_revoke_invalidates_existing_access_token(self):
        cache = InMemoryCache()
        service = CacheTokenService(cache)
        user = User(new_id(), "alice", "hash")
        tokens = service.issue(user)
        self.assertEqual(service.authenticate(tokens["access_token"]), user.id)
        service.revoke_user_tokens(user.id)
        self.assertIsNone(service.authenticate(tokens["access_token"]))

    def test_organization_cycle_is_rejected(self):
        hub = AuthHub.in_memory()
        root = hub.create_organization("Root")
        child = hub.create_organization("Child", parent_id=root.id)
        with self.assertRaises(ValidationError):
            hub.update_organization(root.id, parent_id=child.id)

    def test_module_reregistration_removes_stale_permissions(self):
        hub = AuthHub.in_memory()
        hub.register_module("mcp", "MCP", permissions=[{"id": "mcp:tool:run"}, {"id": "mcp:tool:delete"}])
        hub.register_module("mcp", "MCP", permissions=[{"id": "mcp:tool:run"}])
        self.assertIsNone(hub.repository.get_permission("mcp:tool:delete"))

    def test_module_resources_are_synchronized_and_removed(self):
        hub = AuthHub.in_memory()
        hub.register_module("mcp", "MCP", resources=[
            {"resource_type": "mcp_server", "resource_key": "server-a", "name": "Server A"},
            {"resource_type": "mcp_tool", "resource_key": "tool-a", "name": "Tool A"},
        ])
        self.assertEqual(len(hub.list_resources("mcp")), 2)
        hub.register_module("mcp", "MCP", resources=[
            {"resource_type": "mcp_server", "resource_key": "server-a", "name": "Renamed server"},
        ])
        resources = hub.list_resources("mcp")
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].name, "Renamed server")
        hub.delete_module("mcp")
        self.assertEqual(hub.list_resources("mcp"), [])

    def test_last_system_admin_cannot_be_disabled(self):
        hub = AuthHub.in_memory()
        admin = hub.repository.get_user_by_username("admin")
        with self.assertRaises(ValidationError):
            hub.disable_user(admin.id)


if __name__ == "__main__":
    unittest.main()
