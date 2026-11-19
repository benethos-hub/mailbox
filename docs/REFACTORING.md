# Refactoring the service

Concept of 2026-09-28, in three parts, built the same day. Sections 1
to 7 are the domain: it had grown to 27 modules side by side in one folder, and got
packages by area, and a shape for the change feed like the one
[LOGGING.md](LOGGING.md) section 7 gives the activities. Section 8 is
the data layer and `common`, the same rules applied there. Section 9 is
the code written twice, merged into helpers once the modules are in
place. Section 10 is the MCP server, added later the same day: its
tools in a package, one module per kind. Section 11, a proposal of
2026-10-05, is the migrations of the schema: one class per step.
Section 12 is the work list of 2026-10: the client as a package, the
adapters in parts, and limits on the size of the code. Section 13 is
the client package in parts, of 2026-10-07. Section 17 is the review
of 2026-10-15.
Behaviour, the API and the
OpenAPI document stay as they are
throughout. The rules that came out of it, in short, are
[ARCHITECTURE.md](ARCHITECTURE.md). What the user decided is marked as
decided.

**Built 2026-09-28**, steps 2 to 5 of section 6. Sections 1 and 3.1
describe the domain before. Sections 8 and 9 are built as well, in the
order of 9.4, on one branch: sections 8.1 and 9.1 to 9.3 describe the
code before. Where a finding of section 9 was built otherwise, 9.5 says
so, and the commit that built it says why.

This file is the overview. The sections are in
[refactoring/](refactoring/), under the same numbers.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The domain](refactoring/domain.md) | 1 to 7 | Why and by which principles, the change feed shaped like the activities, the domain in packages, and the order of the work. |
| [The data layer and `common`](refactoring/data.md) | 8 | The same rules applied to the data layer, and what moved to `common`. |
| [Code written twice](refactoring/duplicates.md) | 9 | The duplicates merged into helpers, and what was built otherwise. |
| [The MCP server and the migrations](refactoring/mcp-and-migrations.md) | 10, 11 | The tools of the MCP server in a package, and the migrations of the schema as one class per step. |
| [The client, `mailbox-common` and the limits](refactoring/client-and-common.md) | 12 to 16 | The work list of 2026-10, the client and its records in parts, the fourth package, records and the boundaries. |
| [The review of 2026-10-15](refactoring/review-2026-10-15.md) | 17 | Tests, the adapters, the sizes of the domain, the forms of the UI, flag changes. |

## Every section

- [1. Why](refactoring/domain.md#1-why)
- [2. Principles](refactoring/domain.md#2-principles)
- [3. The change feed, shaped like the activities](refactoring/domain.md#3-the-change-feed-shaped-like-the-activities): [3.1 Today](refactoring/domain.md#31-today) · [3.2 Proposed](refactoring/domain.md#32-proposed)
- [4. The domain in packages](refactoring/domain.md#4-the-domain-in-packages): [4.1 The direction between packages](refactoring/domain.md#41-the-direction-between-packages)
- [5. What else changes](refactoring/domain.md#5-what-else-changes)
- [6. Order of work](refactoring/domain.md#6-order-of-work)
- [7. Questions answered](refactoring/domain.md#7-questions-answered)
- [8. The data layer and `common`](refactoring/data.md#8-the-data-layer-and-common): [8.1 Today](refactoring/data.md#81-today) · [8.2 To `common`](refactoring/data.md#82-to-common) · [8.3 Inside `data`](refactoring/data.md#83-inside-data) · [8.4 The rules, as for the domain](refactoring/data.md#84-the-rules-as-for-the-domain) · [8.5 Order of work](refactoring/data.md#85-order-of-work) · [8.6 Questions answered](refactoring/data.md#86-questions-answered)
- [9. Code written twice](refactoring/duplicates.md#9-code-written-twice): [9.1 More helpers for `common`](refactoring/duplicates.md#91-more-helpers-for-common) · [9.2 Domain and web](refactoring/duplicates.md#92-domain-and-web) · [9.3 Data](refactoring/duplicates.md#93-data) · [9.4 Order, so that nothing overlaps](refactoring/duplicates.md#94-order-so-that-nothing-overlaps) · [9.5 Built otherwise](refactoring/duplicates.md#95-built-otherwise)
- [10. The MCP server](refactoring/mcp-and-migrations.md#10-the-mcp-server): [10.1 Today](refactoring/mcp-and-migrations.md#101-today) · [10.2 Proposed](refactoring/mcp-and-migrations.md#102-proposed) · [10.3 The rules](refactoring/mcp-and-migrations.md#103-the-rules) · [10.4 Order of work](refactoring/mcp-and-migrations.md#104-order-of-work)
- [11. The migrations of the schema](refactoring/mcp-and-migrations.md#11-the-migrations-of-the-schema): [11.1 Today](refactoring/mcp-and-migrations.md#111-today) · [11.2 Proposed](refactoring/mcp-and-migrations.md#112-proposed) · [11.3 A registry, not reflection](refactoring/mcp-and-migrations.md#113-a-registry-not-reflection) · [11.4 Order of work](refactoring/mcp-and-migrations.md#114-order-of-work)
- [12. The work list of 2026-10](refactoring/client-and-common.md#12-the-work-list-of-2026-10): [12.1 Packages and folders](refactoring/client-and-common.md#121-packages-and-folders) · [12.2 Code](refactoring/client-and-common.md#122-code) · [12.3 The limits](refactoring/client-and-common.md#123-the-limits) · [12.4 After the list](refactoring/client-and-common.md#124-after-the-list)
- [13. The client in parts](refactoring/client-and-common.md#13-the-client-in-parts): [13.1 Why](refactoring/client-and-common.md#131-why) · [13.2 Target](refactoring/client-and-common.md#132-target) · [13.3 Order of work](refactoring/client-and-common.md#133-order-of-work)
- [14. The client's records in parts](refactoring/client-and-common.md#14-the-clients-records-in-parts): [14.1 Why](refactoring/client-and-common.md#141-why) · [14.2 Target](refactoring/client-and-common.md#142-target) · [14.3 Order of work](refactoring/client-and-common.md#143-order-of-work)
- [15. A fourth package, `mailbox-common`](refactoring/client-and-common.md#15-a-fourth-package-mailbox-common): [15.1 Why](refactoring/client-and-common.md#151-why) · [15.2 Target](refactoring/client-and-common.md#152-target) · [15.3 Order of work](refactoring/client-and-common.md#153-order-of-work) · [15.4 Groups, and three more moves](refactoring/client-and-common.md#154-groups-and-three-more-moves)
- [16. Records, one settings base, the boundaries](refactoring/client-and-common.md#16-records-one-settings-base-the-boundaries)
- [17. The review of 2026-10-15](refactoring/review-2026-10-15.md#17-the-review-of-2026-10-15): [17.1 Tests](refactoring/review-2026-10-15.md#171-tests) · [17.2 The adapters' duplicates](refactoring/review-2026-10-15.md#172-the-adapters-duplicates) · [17.3 The adapters' layout](refactoring/review-2026-10-15.md#173-the-adapters-layout) · [17.4 The domain's sizes](refactoring/review-2026-10-15.md#174-the-domains-sizes) · [17.5 The UI's forms](refactoring/review-2026-10-15.md#175-the-uis-forms) · [17.6 Flag changes](refactoring/review-2026-10-15.md#176-flag-changes)

