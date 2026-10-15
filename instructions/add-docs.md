# Armory Ledger — Establish Standard Project Documentation

## Working Directory

`/opt/armory-ledger-dev`

## Objective

Establish a standardized documentation structure for Armory Ledger, following the organizational conventions used in the Security Assessment Orchestrator project.

The desired documentation files are:

- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/ROADMAP.md`

Also review or create a root-level `AGENTS.md` to establish clear Codex operating instructions.

## Reference Project

The Security Assessment Orchestrator repository is located at:

`/opt/security-assessment-orchestrator`

Its documentation structure includes the four documents listed above.

If that repository is accessible, review the documentation structure and conventions as a reference. Do not modify the SAO repository or copy SAO-specific technical details into Armory Ledger.

If inaccessible, proceed using the requested structure.

## Phase 1 — Repository Discovery

Before writing documentation:

1. Inspect the Armory Ledger repository structure.
2. Read the README and existing project documentation.
3. Review `docs/v0.1.2-schema-plan.md`.
4. Review existing `AGENTS.md` instructions, if present.
5. Inspect application source code, database models, migrations, API routes, frontend components, and tests.
6. Review existing deployment and development configuration.
7. Review `instructions/range-ammo-filter.md`.
8. Review available Git history where helpful.

Do not modify application code during this task.

## Phase 2 — Documentation Creation

### ARCHITECTURE.md

Document the architecture actually implemented in the repository.

Include, where applicable:

- Technology stack
- Backend architecture
- Frontend architecture
- Database and migration system
- Authentication and authorization
- Firearm inventory data model
- Ammunition inventory and transaction model
- Range-session recording
- Development and production deployment architecture
- Major component relationships

Distinguish implemented behavior from proposed architecture.

Do not invent infrastructure or components that cannot be verified.

### DECISIONS.md

Document significant architectural and product decisions.

Include the rationale and consequences when evidence is available.

Review the existing ammunition inventory implementation and document the current approach to manufacturer lot numbers and logical inventory lots.

Do not present an inferred design choice as an approved historical decision without supporting evidence.

For uncertain decisions, create a section titled "Decisions Requiring Confirmation."

### IMPLEMENTATION_STATUS.md

Establish an accurate implementation baseline.

Identify:

- Completed functionality
- Partially implemented functionality
- Known limitations
- Outstanding defects
- Current testing coverage
- Pending development tasks

Include the ammunition filtering task as pending unless repository evidence shows it has already been implemented.

Do not mark features complete solely because they appear in planning documents.

### ROADMAP.md

Create a practical development roadmap based on existing project plans and implementation gaps.

Include these proposed improvements:

1. Filter range-session ammunition inventory by selected firearm caliber.
2. Support merging compatible ammunition inventory lots while preserving transaction history.
3. Review firearm/ammunition caliber compatibility rules.
4. Improve inventory reconciliation and auditing where needed.

Clearly distinguish existing approved plans from newly proposed improvements.

Do not invent release dates or version commitments.

### AGENTS.md

Create or update root-level Codex instructions covering:

- Repository scope and development environment
- Required documentation review before implementation
- Coding and testing conventions discovered in the repository
- Development versus production safety boundaries
- Database migration precautions
- Documentation maintenance expectations
- Commit, push, and deployment approval requirements

Preserve existing instructions unless they directly conflict with explicitly established project requirements.

## Phase 3 — Documentation Consistency

Review all new documents for consistency.

Ensure:

- Architecture reflects actual implementation.
- Decisions are not confused with planned features.
- Implementation status reflects verified functionality.
- Roadmap items are not represented as completed.
- Existing documentation is preserved.
- File paths and references are accurate.

## Constraints

- Work only in `/opt/armory-ledger-dev`.
- Do not modify application code.
- Do not modify production data or configuration.
- Do not run database migrations.
- Do not deploy.
- Do not commit or push without explicit approval.
- Do not delete or rename existing documentation.
- Do not overwrite an existing AGENTS.md without reviewing and preserving its applicable instructions.

## Deliverables

Report:

1. Documents created or modified.
2. Repository findings used to establish the baseline.
3. Any documentation inconsistencies discovered.
4. Decisions requiring confirmation.
5. Recommended documentation maintenance practices.

Stop after creating and reviewing the documentation. Await approval before committing changes.
