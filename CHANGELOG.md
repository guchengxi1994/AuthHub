# Changelog

All notable changes to AuthHub are documented in this file.

## [0.3.0] - 2026-08-15

### Added

- Register the built-in `authhub` module during bootstrap, with RBAC resources for the management console, users, organizations, roles, permissions, modules, resources, resource instances, audit events, and exact share-recipient lookup.
- Allow restricted operations roles to use the AuthHub management console according to their granted built-in permissions.

### Changed

- Protect AuthHub management APIs with the corresponding `authhub:<resource-type>:<resource-key>:<action>` permission instead of requiring every caller to be a system super administrator.
- Require `authhub:custom:share-recipient:read` to resolve a username for resource sharing. The endpoint remains exact-match only and does not provide a browsable directory.
- Hide unavailable management pages and actions in the bundled admin console using the authenticated permission snapshot.
- Load runtime settings through `pydantic-settings`; process environment variables take precedence over the local `.env` file.

### Security

- Prevent management roles from granting permissions they do not hold, managing system administrators, modifying built-in administrator roles, or overwriting the built-in `authhub` module.
- Require non-super-administrator resource-instance grant managers to delegate only permissions they already hold.

### Fixed

- Use SQLAlchemy `NullPool` for file-backed SQLite development databases so local Windows test databases are released when each operation completes.
