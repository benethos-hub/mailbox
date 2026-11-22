# <img src="../assets/brand/icon.svg" alt="" height="36" align="absmiddle"> Documents

The documents of Mailbox. Each package has a folder of its own, named
like the package. What holds for the whole repository stays here.

**Contents**

- [The packages](#the-packages)
- [The repository](#the-repository)

## The packages

| Package | Documents |
|---|---|
| [mailbox-service](mailbox-service/) | [CONCEPT.md](mailbox-service/CONCEPT.md), the design and where each section is. [ARCHITECTURE.md](mailbox-service/ARCHITECTURE.md), the layers and the rules for every package. [UI.md](mailbox-service/UI.md), [AUTHENTICATION.md](mailbox-service/AUTHENTICATION.md), [PERMISSIONS.md](mailbox-service/PERMISSIONS.md), [LIMITS.md](mailbox-service/LIMITS.md), [LOGGING.md](mailbox-service/LOGGING.md), [AUDIT.md](mailbox-service/AUDIT.md), [UNIFORM.md](mailbox-service/UNIFORM.md), [MICROSOFT.md](mailbox-service/MICROSOFT.md), [GOOGLE.md](mailbox-service/GOOGLE.md). The API contract, [openapi.json](mailbox-service/openapi.json). |
| [mailbox-mcp](mailbox-mcp/) | [CONCEPT.md](mailbox-mcp/CONCEPT.md), sections 8 and 8.1 of the concept. [ARCHITECTURE.md](mailbox-mcp/ARCHITECTURE.md), its modules. Its tools as a client lists them, [mcp-tools.json](mailbox-mcp/mcp-tools.json). |
| [mailbox-client](mailbox-client/) | [CONCEPT.md](mailbox-client/CONCEPT.md), section 8.2 of the concept. [ARCHITECTURE.md](mailbox-client/ARCHITECTURE.md), its modules. Its public interface, [client-interface.json](mailbox-client/client-interface.json). |
| [mailbox-common](mailbox-common/) | [ARCHITECTURE.md](mailbox-common/ARCHITECTURE.md), its modules. Its public interface, [common-interface.json](mailbox-common/common-interface.json). |
| [mailbox-agents](mailbox-agents/) | [CONCEPT.md](mailbox-agents/CONCEPT.md), the design of the agents, with sections of their own. [ARCHITECTURE.md](mailbox-agents/ARCHITECTURE.md), their layers. [LOGGING.md](mailbox-agents/LOGGING.md), their log. [COMPATIBILITY.md](mailbox-agents/COMPATIBILITY.md), which service each release takes. |

The section numbers of the concept and of the architecture count across
the packages of the service: "CONCEPT 8.2" is in the client's folder,
the overview of each lists every section. The agents number their
documents on their own.

## The repository

- [ROADMAP.md](ROADMAP.md): the phases and their state, and in
  [roadmap/](roadmap/) the items of each phase and of the agents.
- [RELEASING.md](RELEASING.md): the steps of a release, in order.
- [LIVE.md](LIVE.md): the live checks, what each one reads, sends,
  changes and deletes.
- [IDEAS.md](IDEAS.md): collected, not yet decided.
- [REFACTORING.md](REFACTORING.md): how the layout came to be.
