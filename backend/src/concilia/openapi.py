import json
import sys
from pathlib import Path

from pydantic import SecretStr

from concilia.api import create_app
from concilia.shared.infrastructure.settings import ApiSettings

DOCUMENT_ONLY_SETTINGS = ApiSettings(
    database_url="postgresql+asyncpg://openapi@localhost/openapi",
    csrf_secret=SecretStr("openapi-document-only"),
    rate_limit_secret=SecretStr("openapi-document-only"),
)


def write_openapi(target: Path) -> None:
    document = create_app(DOCUMENT_ONLY_SETTINGS).openapi()
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    target.write_text(text + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_openapi(Path(sys.argv[1]))
