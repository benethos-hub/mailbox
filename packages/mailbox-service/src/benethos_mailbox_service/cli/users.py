"""``users create-admin`` and ``users set-password``: a one-time password
for a user, made on the host. ``users reset-second-factor``: a user's
second factor removed, when its owner lost every device and the
recovery codes."""

from __future__ import annotations

import argparse

from ..config import load_settings
from .common import Commands, emit, say, stored


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    users = commands.add_parser(
        "users", help="manage users on this host", parents=[option]
    )
    users_commands = users.add_subparsers(dest="users_command", required=True)
    create_admin = users_commands.add_parser(
        "create-admin",
        help="create a user with every right and print a one-time password",
        parents=[option],
    )
    create_admin.add_argument("--name", default="admin")
    set_password = users_commands.add_parser(
        "set-password",
        help="give a user a new one-time password and print it, "
        "e.g. when the last administrator forgot theirs",
        parents=[option],
    )
    set_password.add_argument("name")
    reset = users_commands.add_parser(
        "reset-second-factor",
        help="remove a user's second factor, every method and the recovery "
        "codes, e.g. when the last administrator lost them all",
        parents=[option],
    )
    reset.add_argument("name")


def run(args: argparse.Namespace) -> None:
    """The password alone goes to stdout, so it can be piped on."""
    import anyio

    from ..assembly import opened

    settings = stored(load_settings(args.env_file), "users")
    with opened(settings) as services:
        if args.users_command == "reset-second-factor":
            user = services.factors.reset(args.name)
            say(
                f"Removed the second factor of {user.name} ({user.id}) in "
                f"{settings.database_path}. Its sessions end. It signs in to "
                "the UI with its password alone, and adds a device again on "
                "its page Second factor."
            )
            return
        if args.users_command == "create-admin":
            user, password = anyio.run(services.users.create_admin, args.name)
            done = f"Created user {user.id} ({user.name}) with every right"
        else:
            before = services.auth.user_named(args.name)
            user, password = anyio.run(services.passwords.reset_password, args.name)
            done = f"Gave {user.name} ({user.id}) a new password"
            if before is not None and not before.ui_sign_in:
                done += ", and its UI sign-in, which was off,"
    say(
        f"{done} in {settings.database_path}. Sign in to the UI with this "
        "one-time password, shown this once. The UI then asks for one of "
        "your own:"
    )
    emit(password)
