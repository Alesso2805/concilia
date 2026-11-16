import json
from collections.abc import Sequence
from importlib.resources import files

from concilia.ai.domain.suggestions import Candidate, CreditFacts

PROMPT_VERSION = 1
PROMPT_FILES = {1: "suggest_v1.md"}


def system_prompt(version: int = PROMPT_VERSION) -> str:
    return files("concilia.ai.prompts").joinpath(PROMPT_FILES[version]).read_text(encoding="utf-8")


def user_input(credit: CreditFacts, candidates: Sequence[Candidate]) -> str:
    """Exactly the fields SPEC allows to leave the organization (rule 7); nothing else."""
    return json.dumps(
        {
            "abono": {
                "fecha": credit.booked_on.isoformat(),
                "monto_centimos": credit.amount_cents,
                "descripcion": credit.description,
            },
            "candidatos": [
                {
                    "alias": candidate.alias,
                    "documento": candidate.receivable.doc_number,
                    "cliente": candidate.receivable.customer_name,
                    "saldo_disponible_centimos": candidate.receivable.available_cents,
                    "emision": candidate.receivable.issued_on.isoformat(),
                    "vencimiento": candidate.receivable.due_on.isoformat(),
                }
                for candidate in candidates
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
