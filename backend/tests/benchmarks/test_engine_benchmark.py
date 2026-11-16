import random
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from uuid import UUID

from concilia.matching.domain.engine import run_engine
from concilia.matching.domain.model import Credit, EngineInput, OpenReceivable
from concilia.shared.kernel.normalization import extract_doc_refs, normalize_text

PERIOD = date(2027, 1, 1)
SIZE = 1_000
TIME_LIMIT_SECONDS = 5
FIRST_WORDS = ["COMERCIAL", "DISTRIBUIDORA", "INVERSIONES", "CORPORACION", "IMPORTADORA"]
SECOND_WORDS = ["ANDINA", "DEL SUR", "NORTE", "PACIFICO", "SAN MARTIN", "LOS OLIVOS", "AMAZONICA"]
SUFFIXES = ["SAC", "SA", "SRL", "EIRL"]


def _receivables(rng: random.Random) -> list[OpenReceivable]:
    customers = [
        (
            f"{rng.choice(FIRST_WORDS)} {rng.choice(SECOND_WORDS)} {n} {rng.choice(SUFFIXES)}",
            f"20{rng.randrange(10**9):09d}" if rng.random() < 0.5 else None,
        )
        for n in range(80)
    ]
    receivables = []
    for n in range(SIZE):
        name, tax_id = rng.choice(customers)
        issued_on = PERIOD + timedelta(days=rng.randrange(-45, 10))
        receivables.append(
            OpenReceivable(
                id=UUID(int=10_000 + n),
                doc_number_norm=f"F001-{n + 1}",
                customer_name_norm=normalize_text(name),
                customer_tax_id=tax_id,
                issued_on=issued_on,
                due_on=issued_on + timedelta(days=30),
                available_cents=rng.randrange(5_000, 2_000_000, 100),
            )
        )
    return receivables


def _payments(rng: random.Random, receivables: list[OpenReceivable]) -> list[tuple[int, str]]:
    by_customer: defaultdict[str, list[OpenReceivable]] = defaultdict(list)
    for r in receivables:
        by_customer[r.customer_name_norm].append(r)
    payments: list[tuple[int, str]] = []
    while len(payments) < SIZE:
        paid = rng.choice(receivables)
        name, balance = paid.customer_name_norm, paid.available_cents
        siblings = rng.sample(by_customer[name], k=min(3, len(by_customer[name])))
        match rng.randrange(10):
            case 0 | 1 | 2 | 3:
                payments.append((balance, f"PAGO FACT {paid.doc_number_norm}"))
            case 4:
                documents = " ".join(r.doc_number_norm for r in siblings)
                payments.append((sum(r.available_cents for r in siblings), f"PAGO {documents}"))
            case 5:
                amount = rng.choice([balance - 100, balance * 88 // 100])
                payments.append((amount, f"PAGO {paid.doc_number_norm}"))
            case 6:
                payments.append((sum(r.available_cents for r in siblings), f"TRANSF {name}"))
            case 7:
                payments.append((balance // 2, f"TRANSF {name}"))
                payments.append((balance - balance // 2, f"ABONO {name}"))
            case 8:
                payments.append((balance, f"DEPOSITO {rng.randrange(10**6)}"))
            case _:
                payments.append((rng.randrange(5_000, 2_000_000, 100), "TRANSF INTERBANCARIA"))
    return payments[:SIZE]


def build_input(seed: int = 2027) -> EngineInput:
    rng = random.Random(seed)
    receivables = _receivables(rng)
    credits = [
        Credit(
            id=UUID(int=n + 1),
            booked_on=PERIOD + timedelta(days=rng.randrange(31)),
            amount_cents=amount,
            description_norm=normalize_text(description),
            doc_refs=tuple(extract_doc_refs(description)),
        )
        for n, (amount, description) in enumerate(_payments(rng, receivables))
    ]
    return EngineInput(period=PERIOD, credits=tuple(credits), receivables=tuple(receivables))


def test_the_engine_handles_a_thousand_credits_and_receivables_in_time() -> None:
    engine_input = build_input()

    started = time.perf_counter()
    proposals = run_engine(engine_input)
    elapsed = time.perf_counter() - started

    assert elapsed < TIME_LIMIT_SECONDS
    assert set(Counter(proposal.rule.value for proposal in proposals)) == {
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
    }
