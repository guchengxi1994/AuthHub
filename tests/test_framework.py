import unittest

from auth_hub import AuthHub, AuthHubSettings, InMemoryAuthHubRepository, InMemoryAuditLog, InMemoryCache
from auth_hub.domain.errors import AuthenticationError
from auth_hub.infrastructure import InMemoryTokenService, SimplePasswordHasher
from auth_hub.domain.models import Permission, Role, User, new_id


class FrameworkTests(unittest.TestCase):
    def test_bootstrap_login_and_rbac_decision(self):
        hub = AuthHub.in_memory(AuthHubSettings(admin_password="safe-password"))
        tokens = hub.login("admin", "safe-password")
        self.assertTrue(tokens["access_token"])
        allowed = hub.check_permission(tokens["access_token"], "anything:read")
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


if __name__ == "__main__":
    unittest.main()
