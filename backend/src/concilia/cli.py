import argparse
import asyncio
import getpass
import os
import sys
from uuid import UUID, uuid7

from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.identity.application.registration import Registration, RegistrationService
from concilia.identity.infrastructure.passwords import Argon2PasswordHasher
from concilia.identity.infrastructure.sql import SqlIdentityTransactions
from concilia.shared.infrastructure.clock import SystemClock
from concilia.shared.infrastructure.db import create_engine
from concilia.shared.kernel.clock import Clock


async def create_organization(database_url: str, command: Registration, clock: Clock) -> UUID:
    engine = create_engine(database_url)
    try:
        service = RegistrationService(
            SqlIdentityTransactions(engine, SqlAuditRecorder), Argon2PasswordHasher(), clock
        )
        organization_id, _ = await service.register(command, source="cli")
        return organization_id
    finally:
        await engine.dispose()


def read_password(*, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Admin password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise SystemExit("passwords do not match")
    return password


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="concilia")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-org", help="create an organization and its first admin")
    create.add_argument("--name", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument(
        "--password-stdin", action="store_true", help="read the password from standard input"
    )
    arguments = parser.parse_args(argv)

    password = read_password(from_stdin=arguments.password_stdin)
    command = Registration(
        uuid7(), arguments.name, arguments.display_name, arguments.email, password
    )
    organization_id = asyncio.run(
        create_organization(os.environ["CONCILIA_MIGRATIONS_DATABASE_URL"], command, SystemClock())
    )
    sys.stdout.write(f"organization {organization_id} created\n")


if __name__ == "__main__":
    main()
