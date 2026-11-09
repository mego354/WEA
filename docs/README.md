# WEA Pharma ERP — Documentation Index

This directory contains the authoritative technical documentation for the WEA Pharma ERP project.
Every contributor and AI agent must consult these documents before modifying system behavior.

---

## Authoritative Documentation Set

| Document | Description |
|---|---|
| [**ARCHITECTURE.md**](ARCHITECTURE.md) | High-level system architecture, app dependencies, layered design, core models, and data flows. |
| [**BUSINESS_LOGIC.md**](BUSINESS_LOGIC.md) | Core business logic, status machines, visit GPS rules, inventory memos, sales/purchase lifecycles, and audit logging. |
| [**AUTHORIZATION.md**](AUTHORIZATION.md) | Canonical roles, direct user permissions (`has_custom_permissions`), configurable scopes (`ScopeResolutionService`), and territorial oversight. |
| [**UI_UX_GUIDE.md**](UI_UX_GUIDE.md) | Arabic RTL design system, compact UI standards, drawer filter persistence, table column manager, and mobile patterns. |
| [**CODING_STANDARDS.md**](CODING_STANDARDS.md) | Engineering standards, IDOR prevention, concurrency locking (`select_for_update`), transaction safety, and clean code principles. |
| [**TESTING.md**](TESTING.md) | Consolidated single-test-file architecture (`app/tests.py`), test execution commands, coverage inventory, and testing standards. |
| [**DEPLOYMENT.md**](DEPLOYMENT.md) | Installation instructions, environment variables, Linux/PythonAnywhere deployment, static file management, and backups. |
| [**API_REFERENCE.md**](API_REFERENCE.md) | Specifications for JSON and AJAX endpoints, request/response contracts, and error responses. |
| [**CLEANUP_AUDIT.md**](CLEANUP_AUDIT.md) | Comprehensive audit inventory of cleaned directories, consolidated tests, and relocated assets. |
| [**CLEANUP_REPORT.md**](CLEANUP_REPORT.md) | Final cleanup verification report, metrics, deleted file counts, and test execution results. |

---

## Agent Engineering Contract

For AI coding agents, the primary entry point is the root contract:
[`AGENTS.md`](../AGENTS.md)
