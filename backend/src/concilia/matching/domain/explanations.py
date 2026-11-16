from collections.abc import Sequence

from concilia.matching.domain.amounts import CENTS_PER_SOL

PERCENT_IN_BASIS_POINTS = 100


def format_pen(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    soles, rest = divmod(abs(cents), CENTS_PER_SOL)
    return f"S/ {sign}{soles:,}.{rest:02d}"


def format_rate(rate_bp: int) -> str:
    whole, rest = divmod(rate_bp, PERCENT_IN_BASIS_POINTS)
    decimals = f".{rest:02d}".rstrip("0") if rest else ""
    return f"{whole}{decimals} %"


def join_documents(documents: Sequence[str]) -> str:
    if len(documents) == 1:
        return documents[0]
    return f"{', '.join(documents[:-1])} y {documents[-1]}"


def exact(document: str) -> str:
    return f"La descripción menciona {document} y el monto coincide con su saldo."


def several_documents(documents: Sequence[str]) -> str:
    return (
        f"La descripción menciona {join_documents(documents)} "
        "y la suma de sus saldos coincide con el abono."
    )


def within_tolerance(document: str, difference_cents: int) -> str:
    return (
        f"La descripción menciona {document} y la diferencia de "
        f"{format_pen(difference_cents)} está dentro de la tolerancia."
    )


def detraction(document: str, difference_cents: int, rate_bp: int) -> str:
    return (
        f"La descripción menciona {document} y la diferencia de "
        f"{format_pen(difference_cents)} corresponde a una detracción del {format_rate(rate_bp)}."
    )
