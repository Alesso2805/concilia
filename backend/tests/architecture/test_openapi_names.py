from concilia.api import create_app
from concilia.openapi import DOCUMENT_ONLY_SETTINGS


def test_every_schema_in_the_contract_has_a_plain_name() -> None:
    """FastAPI renames two models that share a name to their module paths, which renames the
    generated client's types and breaks the frontend; give each response or request model a
    unique name instead."""
    schemas = create_app(DOCUMENT_ONLY_SETTINGS).openapi()["components"]["schemas"]

    assert [name for name in schemas if "__" in name or name.startswith("concilia")] == []
