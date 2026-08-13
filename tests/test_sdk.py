import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from auth_hub import AuthHub, AuthHubSettings
from auth_hub.api import _module_registrar_actor
from auth_hub_client import ModuleManifest, PermissionSpec, ResourceSpec


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

    def test_registration_key_allows_service_sync_without_admin_token(self):
        hub = AuthHub.in_memory(AuthHubSettings(module_registration_key="test-registration-key"))
        self.assertEqual(_module_registrar_actor(hub, None, "test-registration-key"), "service:module-registration")
        with self.assertRaises(Exception):
            _module_registrar_actor(hub, None, "wrong-key")


if __name__ == "__main__":
    unittest.main()
