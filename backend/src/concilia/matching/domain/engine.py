from collections.abc import Callable

from concilia.matching.domain import reference_rules
from concilia.matching.domain.model import EngineInput, Proposal
from concilia.matching.domain.state import RunState

RULES_VERSION = 1
RULES: tuple[Callable[[RunState], None], ...] = (
    reference_rules.exact,
    reference_rules.several_documents,
    reference_rules.reference_with_difference,
)


def run_engine(engine_input: EngineInput) -> list[Proposal]:
    state = RunState(engine_input)
    for rule in RULES:
        rule(state)
    return state.proposals
