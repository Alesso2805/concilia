from collections.abc import Callable

from concilia.matching.domain import customer_rules, reference_rules
from concilia.matching.domain.model import EngineInput, Proposal
from concilia.matching.domain.state import RunState

RULES_VERSION = 1
RULES: tuple[Callable[[RunState], None], ...] = (
    reference_rules.exact,
    reference_rules.several_documents,
    reference_rules.reference_with_difference,
    customer_rules.same_customer,
    customer_rules.paid_in_parts,
    customer_rules.amount_and_date,
)


def run_engine(engine_input: EngineInput) -> list[Proposal]:
    state = RunState(engine_input)
    for rule in RULES:
        rule(state)
    return state.proposals
