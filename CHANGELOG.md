# Changelog

All notable changes to AuthHub are documented in this file.

## [0.5.3] - 2026-08-17

### Added

- Add client-side business-resource filters for resource name or key, module, permission category, and resource type, with a result count and reset action.

## [0.5.2] - 2026-08-17

### Changed

- Rename record-level authorization controls in the management console to distinguish all-user access from selected-user authorization.
- Explain that all-user access bypasses role and record-scope checks, while selected-user authorization affects only one user and one record without changing roles or all-user access.
- Present all-user operations as available to all signed-in users instead of showing their underlying owner/organization scope labels.

## [0.5.1] - 2026-08-17

### Fixed

- Add module-level select-all controls to role and record permission selectors.
- Fix resource-level select-all so native checkbox state correctly propagates to every enabled permission and keeps module/resource counts synchronized.

## [0.5.0] - 2026-08-17

### Added

- Make newly registered business-data records publicly accessible for enabled `view`/`read` permissions by default, with an explicit empty list for private records and `null` to restore the default.
- Allow a record owner or system administrator to configure public operations through external-ID and internal-ID APIs, with matching Python SDK methods.
- Display and edit record-level public operations in the management console.

### Changed

- Preserve the authenticated creator as the owner when a direct user registration omits `owner_user_id`; service/outbox registrations can continue to provide ownership explicitly.
- Harden public-permission metadata parsing and synchronize framework, client SDK, React SDK, and static asset versions to `0.5.0`.

## [0.4.0] - 2026-08-15

### Added

- Classify every permission as AuthHub management, business operation, or business data without requiring a database schema migration; expose the derived category and record-tracking capability through the resource and permission APIs.
- Expose matching permission-category helpers in the Python client SDK and validate manifests before registration.

### Changed

- Restrict `owner` and `organization` scopes, data-record registration, record-level authorization, and per-record sharing to `entity` and `custom` business data resources.
- Reorganize the management console around the three permission categories. Operation resources now show global-only scope, while data records and record sharing are presented as one workflow.
- Rename the management-console resource views to clarify the distinction between business resources and registered data records.
- Document that a data-changing business route can require both a business operation permission and a record-level business data permission.

### Migration

- Resource instances previously used for API, page, or UI-operation resources are no longer valid for new record-level authorization. Model the shareable object as an `entity` or `custom` business data resource and register its records through the SDK outbox.

## [0.3.1] - 2026-08-15

### Changed

- Separate AuthHub built-in permissions from business-system permissions in the admin console.
- Group large permission sets by permission category, module, and resource; collapse groups by default when the list is large.
- Automatically expand selected groups and search matches, with per-resource select-all controls in permission assignment forms.

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
