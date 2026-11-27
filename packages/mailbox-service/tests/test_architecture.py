"""The layering, checked instead of only written down.

web -> domain -> data, never the other way. A single reverse import is enough
to undo the split, and it happens by accident: a data module needs one domain
rule, imports it, and the data layer can no longer be used without the domain.
This test reads every import of the package and fails on the first one that
breaks a rule. The packages inside the domain and the data layer are
test_packages.py's, the assembly and the command line test_assembly.py's.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from .source_helpers import (
    ASSEMBLY,
    HELPERS,
    PACKAGE,
    ROOT,
    imports,
    modules,
    own_part,
)

# Lower number = lower layer. A module may import its own layer and everything
# below it, never above.
LAYERS = {"data": 0, "domain": 1, "web": 2}

# Outside the layers. Read from every layer, so they import none of them.
# A module (config.py) or a package (common/).
CROSS_CUTTING = {"config", "errors", "common"}

# Shared helpers: the standard library, anyio, the common package, idna
# (host names as IDNA 2008, hosts.py) and each other, nothing else.
HELPER_LIBRARIES = {"anyio", "benethos_mailbox_common", "idna"}

# Web frameworks live in the web layer. assembly/web.py builds the app, so it
# may too.
WEB_LIBRARIES = {"fastapi", "starlette"}

# One library, one home (docs/mailbox-service/ARCHITECTURE.md): the only module, or
# package, allowed to import each.
LIBRARY_HOMES = {
    "cryptography": f"{PACKAGE}.data.secrets.cipher",
    "fido2": f"{PACKAGE}.data.secrets.passkeys",
    "keyring": f"{PACKAGE}.data.secrets.keys",
    "sqlite3": f"{PACKAGE}.data.storage.sqlite",
    "sqlalchemy": f"{PACKAGE}.data.storage.sql",
    "alembic": f"{PACKAGE}.data.storage.sql.revisions",
    "imapclient": f"{PACKAGE}.data.protocols.imap",
    # The errors and the quoting of the standard library beside IMAPClient.
    "imaplib": f"{PACKAGE}.data.protocols.imap",
    "imap_tools": f"{PACKAGE}.data.mail.parse",
    # Messages in RFC 5322, whatever protocol carries them.
    "email": f"{PACKAGE}.data.mail",
    "smtplib": f"{PACKAGE}.data.protocols.smtp",
    # TLS contexts, for every protocol that connects.
    "ssl": f"{PACKAGE}.data.protocols.transport",
    "poplib": f"{PACKAGE}.data.protocols.pop3",
    "httpx": f"{PACKAGE}.data.protocols.http",
    "dns": f"{PACKAGE}.data.discovery.dns",
    "defusedxml": f"{PACKAGE}.data.discovery.autoconfig",
    "publicsuffixlist": f"{PACKAGE}.data.discovery.suffix",
    "idna": f"{PACKAGE}.common.hosts",
    "jinja2": f"{PACKAGE}.web.pages.templates",
    # The folders of the operating system come from the common package.
    "platformdirs": "benethos_mailbox_common.paths.folders",
    # And the settings file.
    "pydantic_settings": "benethos_mailbox_common.settings.files",
    "segno": f"{PACKAGE}.web.pages.qr",
    "prometheus_client": f"{PACKAGE}.web.api.exposition",
    # The server of the command serve.
    "uvicorn": f"{PACKAGE}.cli.serve",
}
# Libraries used across the layers, each for a reason of its own: the
# records and the async runtime of the whole service, the shared package.
# The web libraries have a rule of their own.
UNHOMED = {"pydantic", "anyio", "benethos_mailbox_common"} | WEB_LIBRARIES


def test_no_module_imports_a_higher_layer() -> None:
    violations = []
    for name, path in modules():
        own = LAYERS.get(own_part(name) or "")
        if own is None:
            continue
        for imported, line in imports(path):
            other = LAYERS.get(own_part(imported) or "")
            if other is not None and other > own:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "import against the layering:\n  " + "\n  ".join(violations)


def _cross_cutting_files(part: str) -> list[Path]:
    module, package = ROOT / f"{part}.py", ROOT / part
    if package.is_dir():
        return sorted(package.rglob("*.py"))
    assert module.exists(), f"{part}.py is missing"
    return [module]


def test_cross_cutting_modules_import_no_layer() -> None:
    for part in CROSS_CUTTING:
        for path in _cross_cutting_files(part):
            inside = [
                imported
                for imported, _ in imports(path)
                if own_part(imported) in LAYERS or own_part(imported) in ASSEMBLY
            ]
            assert not inside, f"{path.name} imports from the layers: {inside}"


def test_shared_helpers_use_the_standard_library_and_anyio() -> None:
    """common/ holds helpers that know no layer, so it depends on nothing
    but the standard library, anyio, how the project writes concurrency,
    and idna, how it writes a host name."""
    violations = []
    for path in _cross_cutting_files(HELPERS):
        for imported, line in imports(path):
            top = imported.split(".")[0]
            own = imported.startswith(f"{PACKAGE}.{HELPERS}")
            if own or top in HELPER_LIBRARIES:
                continue
            if top not in sys.stdlib_module_names:
                violations.append(f"{path.name}:{line} imports {imported}")
    assert not violations, "common/ beyond its libraries:\n  " + "\n  ".join(violations)


def test_the_domain_picks_no_storage() -> None:
    """Which store is used is decided where the app is assembled. A domain
    service that makes its own would keep data where nobody looks."""
    violations = []
    for name, path in modules():
        if own_part(name) != "domain":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.startswith(("InMemory", "Sql")):
                        violations.append(f"{name}:{node.lineno} {alias.name}")
    assert not violations, "storage chosen in the domain:\n  " + "\n  ".join(violations)


def test_the_database_stays_behind_the_storage_package() -> None:
    """Outside ``data/storage`` the store is reached through the package,
    so another database replaces ``sql/`` and ``sqlite/`` and nothing
    else."""
    inside = f"{PACKAGE}.data.storage"
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in modules()
        if not name.startswith(inside)
        for imported, line in imports(path)
        if imported.startswith(f"{inside}.sql")
    ]
    assert not violations, "the database reached directly:\n  " + "\n  ".join(
        violations
    )


def test_sql_reaches_sqlite_in_one_place() -> None:
    """``sql/`` speaks SQLAlchemy, ``sqlite/`` holds the old migrations of
    the file: ``database``, which hands the storage of mailbox-common the
    shape of the service, gives it the old steps, and no other module of
    ``sql/`` reaches there."""
    sql = f"{PACKAGE}.data.storage.sql"
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in modules()
        if name.startswith(f"{sql}.") and name != f"{sql}.database"
        for imported, line in imports(path)
        if imported.startswith(f"{PACKAGE}.data.storage.sqlite")
    ]
    assert not violations, "sqlite/ reached from sql/:\n  " + "\n  ".join(violations)


def test_the_files_beside_a_database_are_named_in_sqlite_alone() -> None:
    """What SQLite keeps beside a database, its journals and its shared
    memory, is named under ``data/storage/sqlite`` alone, so another
    database replaces ``sqlite/`` and nothing else (ARCHITECTURE 8)."""
    inside = f"{PACKAGE}.data.storage.sqlite"
    sidecar = re.compile(r"""["'](-journal|-wal|-shm)["']""")
    found = [
        name
        for name, path in modules()
        if not name.startswith(inside) and sidecar.search(path.read_text("utf-8"))
    ]
    assert found == [], "the files of SQLite named outside sqlite/: " + ", ".join(found)


def test_web_framework_stays_in_the_web_layer() -> None:
    """Under web/, and in assembly/web.py, which builds the app
    (docs/mailbox-service/ARCHITECTURE.md 7), not in the rest of what assembles."""
    violations = []
    for name, path in modules():
        if own_part(name) == "web" or name == f"{PACKAGE}.assembly.web":
            continue
        for imported, line in imports(path):
            if imported.split(".")[0] in WEB_LIBRARIES:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "web framework outside web/:\n  " + "\n  ".join(violations)


def test_tls_trust_is_chosen_in_one_place() -> None:
    """Every HTTP client verifies against one store, the CAs of the system:
    ``verify=`` stands in ``data/protocols/http/base.py`` alone."""
    one = f"{PACKAGE}.data.protocols.http.base"
    found = [
        name
        for name, path in modules()
        if name != one and re.search(r"verify=", path.read_text("utf-8"))
    ]
    assert found == [], "an HTTP client choosing its own trust store"


def test_providers_are_reached_through_the_registry() -> None:
    """Outside data/providers/, only the package itself is imported."""
    prefix = f"{PACKAGE}.data.providers"
    violations = []
    for name, path in modules():
        if name.startswith(prefix):
            continue
        for imported, line in imports(path):
            if imported.startswith(prefix + "."):
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "provider module imported directly:\n  " + "\n  ".join(
        violations
    )


def test_concurrency_is_written_with_anyio() -> None:
    """The one concurrency library (docs/mailbox-service/ARCHITECTURE.md 7, rule 4): no
    module imports asyncio, so every part runs on either event loop."""
    offenders = [
        f"{name}:{line}"
        for name, path in modules()
        for module, line in imports(path)
        if module == "asyncio" or module.startswith("asyncio.")
    ]
    assert offenders == []


def test_host_names_are_written_as_idna_2008_in_one_place() -> None:
    """Python's codec ``idna`` is IDNA 2003, which makes ``strasse.de`` of
    ``straße.de``. Host names are written by ``common/hosts.py`` alone."""
    codec = re.compile(r"""(?:en|de)code\(\s*["']idna["']""")
    found = [n for n, path in modules() if codec.search(path.read_text("utf-8"))]
    assert found == [f"{PACKAGE}.common.hosts"], "IDNA 2003 outside common/hosts.py"


def test_every_layer_exists_and_is_documented() -> None:
    """A layer without a docstring is a folder, not a decision."""
    for layer in LAYERS:
        init = ROOT / layer / "__init__.py"
        assert init.exists(), f"{layer}/__init__.py is missing"
        docstring = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8")))
        assert docstring, f"{layer}/__init__.py has no docstring"


def test_each_wrapped_library_has_one_home() -> None:
    violations = []
    for name, path in modules():
        for imported, line in imports(path):
            home = LIBRARY_HOMES.get(imported.split(".")[0])
            if home is not None and name != home and not name.startswith(home + "."):
                violations.append(f"{name}:{line} imports {imported}, home is {home}")
    assert not violations, "library outside its home:\n  " + "\n  ".join(violations)


def test_every_library_has_a_home_or_a_reason() -> None:
    """A library without a home could be imported anywhere: each one the
    service imports is in ``LIBRARY_HOMES`` or in ``UNHOMED``."""
    loose = sorted(
        {
            f"{top} ({name}:{line})"
            for name, path in modules()
            for imported, line in imports(path)
            for top in [imported.split(".")[0]]
            if top
            and top not in sys.stdlib_module_names
            and top not in (PACKAGE, "__future__")
            and top not in LIBRARY_HOMES
            and top not in UNHOMED
        }
    )
    assert not loose, "a library without a home:\n  " + "\n  ".join(loose)


def test_no_module_is_named_like_its_package() -> None:
    """The service of a package is service.py, and a module is never
    named like the package that holds it (ARCHITECTURE 5.6)."""
    named = [
        path.relative_to(ROOT).as_posix()
        for path in sorted(ROOT.rglob("*.py"))
        if path.stem == path.parent.name
    ]
    assert not named, "named like its package:\n  " + "\n  ".join(named)
