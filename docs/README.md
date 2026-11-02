# Documentation Index

`AGENTS.md` at the repository root is the **mandatory engineering contract** for AI coding agents and human developers making changes to this repository. This directory contains the authoritative, specialized guides that `AGENTS.md` points to.

---

## Authoritative Documentation Map

| Document | Purpose | When to Read |
|---|---|---|
| [**architecture.md**](architecture.md) | Actual project layout, apps, model relationships, request lifecycle, service layer, transaction conventions, and cross-app workflows. | When changing project structure, adding models/fields, adding URLs, or modifying multi-app business logic. |
| [**business-rules-and-permissions.md**](business-rules-and-permissions.md) | Canonical enterprise roles, main-area organizational hierarchy, data isolation (`get_scoped_queryset`), anti-self-approval, and permissions matrix. | Before any change touching authorization, roles, queries, or user/customer scoping. |
| [**ui-ux-guidelines.md**](ui-ux-guidelines.md) | Arabic RTL design system, teal brand tokens (`#27bebe`), mobile app-like layouts, responsive cards vs tables, and UX standards. | When modifying templates, CSS, JavaScript, navigation, forms, modals, or tables. |
| [**coding-standards.md**](coding-standards.md) | Naming conventions, ORM optimization, transaction management, SOLID/DRY principles, exception handling, and dead-code prevention. | Before writing, refactoring, or reviewing any Python or template code. |
| [**testing-strategy.md**](testing-strategy.md) | Test runner commands, test organization per app, required test categories, regression policies, and verification standards. | When adding, updating, or running automated test cases. |
| [**audit-logging.md**](audit-logging.md) | Enterprise security audit trail (`SecurityAuditLog`) and workflow trail (`ApprovalAuditLog`), mutation coverage, and immutability rules. | When adding or modifying any mutation path (views, APIs, services, management commands). |
| [**api-contracts.md**](api-contracts.md) | Active JSON/AJAX endpoints, HTTP status codes, request/response schemas, customer search APIs, and error envelopes. | When touching AJAX endpoints, JSON responses, or frontend fetch calls. |
| [**maintenance-and-deployment.md**](maintenance-and-deployment.md) | Local environment setup, environment variables, database configuration, static/media management, and production operations. | When configuring local setup, dependencies, migrations, or release deployment. |

---

## Relationship Between `AGENTS.md` and Detailed Guides

- **`AGENTS.md`** is the concise, high-priority rulebook that must be reviewed at the beginning of every AI coding task. It establishes non-negotiable architectural constraints, mandatory business rules, and completion checklists.
- **`docs/*.md`** provide in-depth operational specifications, schema details, permission matrices, and implementation conventions.
- If `AGENTS.md` and a detailed guide ever disagree, **inspect the actual codebase first**, verify the live implementation, and then update both documents together.

---

## How to Keep Documentation Current

1. **Inspect Code First:** Never document hypothetical or planned features as if they are already implemented. Clearly distinguish between **implemented behavior**, **known limitations**, and **proposals**.
2. **Synchronize Changes:** Whenever models, endpoints, permissions, audit events, or architectural rules change, update the relevant guide in `docs/` and `AGENTS.md` in the exact same task.
3. **No Redundant Documents:** Do not create parallel or duplicate documentation files. Keep the documentation suite minimal, organized, and authoritative.
4. **Historical Archive:** Historical documentation, point-in-time QA reports, and reference ERP inventories are preserved in [`archive/`](archive/README.md). Do not treat archived notes as current engineering rules.

