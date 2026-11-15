from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

BACKEND_ROOT = Path(__file__).resolve().parents[2]
INIT_DIR = BACKEND_ROOT.parent / "infra" / "postgres" / "init"
POSTGRES_IMAGE = "postgres:17.12"
ROLE_PASSWORDS = {
    "concilia_owner": "owner-test",
    "concilia_app": "app-test",
    "concilia_worker": "worker-test",
    "concilia_backup": "backup-test",
}


@dataclass(frozen=True)
class DatabaseUrls:
    host: str
    port: int

    def for_role(self, role: str) -> str:
        password = ROLE_PASSWORDS[role]
        return f"postgresql+asyncpg://{role}:{password}@{self.host}:{self.port}/concilia"


def migrate(url: str) -> None:
    config = Config(toml_file=str(BACKEND_ROOT / "pyproject.toml"))
    config.attributes["url"] = url
    command.upgrade(config, "head")


@contextmanager
def running_database() -> Iterator[DatabaseUrls]:
    container = PostgresContainer(
        POSTGRES_IMAGE, username="postgres", password="postgres-test", dbname="postgres"
    )
    container.with_volume_mapping(str(INIT_DIR), "/docker-entrypoint-initdb.d", "ro")
    for role, password in ROLE_PASSWORDS.items():
        container.with_env(f"{role.upper()}_PASSWORD", password)
    with container:
        urls = DatabaseUrls(
            container.get_container_host_ip(), int(container.get_exposed_port(5432))
        )
        migrate(urls.for_role("concilia_owner"))
        yield urls
