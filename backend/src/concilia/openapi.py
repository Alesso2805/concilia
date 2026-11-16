import json
import sys
from pathlib import Path

from concilia.api import create_app


def write_openapi(target: Path) -> None:
    document = json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False)
    target.write_text(document + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_openapi(Path(sys.argv[1]))
