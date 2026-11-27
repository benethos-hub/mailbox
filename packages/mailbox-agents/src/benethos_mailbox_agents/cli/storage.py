"""``storage``: the database of one agent and instance on a PostgreSQL
server.

``provision`` prints what an administrator runs once for it: the role,
the database it owns, closed to every other role, and the roles the
cockpit reads with. With ``--apply`` it runs that itself, signed in as
the administrator an address and a password file name for this call
alone, and sets the password the settings of the instance name. Role
and database are those of ``DATABASE_URL``, or else
``agent_<agent>_<instance>``.

``move`` copies the state file of the agent and instance into the
database ``DATABASE_URL`` names, which holds no table yet, and compares
every table on both sides. The file stays as it was, and neither side
may be in use by a running agent. With ``--check`` it only holds every
value of the file to its column. See docs/mailbox-agents/concept/state.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benethos_mailbox_common.storage import (
    move as moving,
)
from benethos_mailbox_common.storage import (
    names,
    server_place,
    server_provision,
    server_url,
)

from ..contract import load_agent, state_name
from ..errors import STATE_ERRORS, ConfigError, StateFileError
from ..settings import PREFIX, Settings
from ..settings.database import server_of
from ..store import path_for
from ..store.shape import SHAPE

__all__ = ["LOGIN", "READER", "add", "move", "provision", "suggested_name"]

# The role that may read the database of every instance, without
# signing in, and the role the cockpit signs in with, a member of it.
READER = "agents_read"
LOGIN = "agents_cockpit"


def add(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """The command ``storage`` and its actions."""
    storage = sub.add_parser(
        "storage", help="the database of an agent and instance on PostgreSQL"
    )
    actions = storage.add_subparsers(dest="action", metavar="action", required=True)
    found = actions.add_parser(
        "provision",
        help="what an administrator runs once for the database of an instance, "
        "or run it with --apply",
    )
    found.add_argument("--agent", required=True, help="the agent, such as counting")
    found.add_argument(
        "--apply",
        action="store_true",
        help="run it, as the administrator --admin-url names",
    )
    found.add_argument(
        "--admin-url",
        default=None,
        help=f"with --apply: the administrator as {server_url.URL_FORM}",
    )
    found.add_argument(
        "--admin-password-file",
        type=Path,
        default=None,
        help="with --apply: the file that holds the administrator's password",
    )
    found.set_defaults(handler=provision)
    found = actions.add_parser(
        "move",
        help="copy the state file into the database of DATABASE_URL and "
        "compare it. Stop the agent first.",
    )
    found.add_argument("--agent", required=True, help="the agent, such as counting")
    found.add_argument(
        "--check",
        action="store_true",
        help="hold every value of the file to its column, write nothing",
    )
    found.set_defaults(handler=move)


def suggested_name(agent: str, instance: str | None) -> str:
    """The name of the role and the database of an instance where the
    settings name none: ``agent_<agent>``, with an instance
    ``agent_<agent>_<instance>``, its dashes as underscores. One longer
    than PostgreSQL takes is refused, never shortened."""
    name = f"agent_{agent}"
    if instance:
        name += "_" + instance.replace("-", "_")
    if not names.is_plain_name(name):
        raise ConfigError(
            f"{name} is longer than the 63 characters of a name in PostgreSQL:"
            f" name the role and the database in {PREFIX}DATABASE_URL"
        )
    return name


def _instance(agent: str, settings: Settings) -> server_provision.Instance:
    if settings.database_url:
        named = server_url.server_at(settings.database_url, "")
        role, database = named.role, named.database
    else:
        role = database = suggested_name(agent, settings.instance)
    return server_provision.Instance(
        role=role, database=database, reader=READER, login=LOGIN
    )


def provision(args: argparse.Namespace, settings: Settings) -> int:
    agent = load_agent(args.agent)
    label = f"{agent.name}/{settings.instance}" if settings.instance else agent.name
    found = _instance(agent.name, settings)
    if not args.apply:
        _print_plan(found, settings)
        return 0
    if not args.admin_url or args.admin_password_file is None:
        raise ConfigError("--apply needs --admin-url and --admin-password-file")
    if settings.storage != "postgres":
        raise ConfigError(
            f"--apply makes the database the settings name: set {PREFIX}STORAGE"
            f"=postgres, {PREFIX}DATABASE_URL and {PREFIX}DATABASE_PASSWORD_FILE"
        )
    problem = server_url.url_problem(args.admin_url, "--admin-url")
    if problem is not None:
        raise ConfigError(problem)
    password = settings.database_server().password
    admin = server_of(
        args.admin_url,
        args.admin_password_file,
        tls=settings.database_tls,
        ca_file=settings.database_ca_file,
        setting="--admin-password-file",
    )
    done = server_provision.make_instance(admin, found, password, SHAPE)
    print(
        f"{label}: made {', '.join(done.made)} on {admin.host}:{admin.port}."
        " The agent starts on it as its settings say."
    )
    if READER not in settings.database_readers:
        print(
            f"{label}: the cockpit reads it once {PREFIX}DATABASE_READERS"
            f" names {READER}"
        )
    return 0


def _print_plan(found: server_provision.Instance, settings: Settings) -> None:
    for line in server_provision.instance_statements(found, STATE_ERRORS):
        print(f"{line};")
    print("-- Once per server, where they are missing: the roles of the cockpit.")
    for line in server_provision.reading_statements(found):
        print(f"{line};")
    print(
        f"-- Set the password of {found.role} to the one in the file"
        f" {PREFIX}DATABASE_PASSWORD_FILE names, then name in the settings:"
    )
    host = "<host>:<port>"
    if settings.database_url:
        named = server_url.server_at(settings.database_url, "")
        host = f"{named.host}:{named.port}"
    print(f"--   {PREFIX}STORAGE=postgres")
    print(
        f"--   {PREFIX}DATABASE_URL=postgresql://{found.role}@{host}/{found.database}"
    )
    print(f"--   {PREFIX}DATABASE_READERS={READER}")


def move(args: argparse.Namespace, settings: Settings) -> int:
    agent = load_agent(args.agent)
    source = path_for(settings.data_dir, state_name(agent.name, settings.instance))
    if not settings.database_url:
        raise ConfigError(
            f"storage move goes into the database {PREFIX}DATABASE_URL names:"
            " set it and its password file"
        )
    problem = server_url.url_problem(settings.database_url)
    if problem is not None:
        raise ConfigError(problem)
    target = settings.database_server()
    where = f"the database {target.database} on {target.host}:{target.port}"
    try:
        if args.check:
            found = moving.check_move(SHAPE, source)
            print(
                f"Every value of {source} fits its column: {found.rows} rows"
                f" in {found.tables} tables. Nothing was written."
            )
            return 0
        _schema_made(target)
        moved = moving.move_records(SHAPE, source, target)
    except moving.MoveError as exc:
        raise StateFileError(str(exc)) from None
    print(
        f"Moved {moved.rows} rows in {moved.tables} tables from {source} to"
        f" {where}, compared table by table. The file is as it was. Set"
        f" {PREFIX}STORAGE=postgres to start the agent on the database."
    )
    return 0


def _schema_made(server: server_place.Server) -> None:
    """The schema of the role, made where it is missing, as the agent
    makes it at its first start: a move goes into it."""
    place = server_place.ServerPlace(server, SHAPE, make_schema=True)
    try:
        place.open(SHAPE.newest, SHAPE.newest)
    finally:
        place.close()
