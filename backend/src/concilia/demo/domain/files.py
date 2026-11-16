from collections.abc import Iterable

from concilia.demo.domain.dataset import Dataset, DemoMovement, DemoReceivable

STATEMENT_COLUMNS = ("Fecha", "Descripción", "Operación", "Monto")
RECEIVABLE_COLUMNS = ("Cliente", "RUC", "Documento", "Emisión", "Vencimiento", "Monto")
DOWNLOAD_OVERLAP = 3


def _soles(cents: int, decimal: str, thousands: str) -> str:
    whole, rest = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", thousands)
    return f"{'-' if cents < 0 else ''}{grouped}{decimal}{rest:02d}"


def statement_csv(movements: Iterable[DemoMovement]) -> bytes:
    """Semicolon CSV with decimal comma, like a Peruvian bank export opened in Excel."""
    lines = [";".join(STATEMENT_COLUMNS)]
    lines += [
        ";".join(
            (
                movement.booked_on.strftime("%d/%m/%Y"),
                movement.description,
                movement.operation_number,
                _soles(movement.amount_cents, ",", "."),
            )
        )
        for movement in movements
    ]
    return ("\n".join(lines) + "\n").encode()


def receivables_csv(receivables: Iterable[DemoReceivable]) -> bytes:
    """Comma CSV with decimal point, as the generic receivables template expects."""
    lines = [",".join(RECEIVABLE_COLUMNS)]
    lines += [
        ",".join(
            (
                receivable.customer_name,
                receivable.customer_tax_id or "",
                receivable.doc_number,
                receivable.issued_on.strftime("%d/%m/%Y"),
                receivable.due_on.strftime("%d/%m/%Y"),
                _soles(receivable.amount_cents, ".", ""),
            )
        )
        for receivable in receivables
    ]
    return ("\n".join(lines) + "\n").encode()


def download_statement(dataset: Dataset) -> bytes:
    """The month to import by hand, starting with the last rows of the month before, as bank
    exports often overlap; the preview shows them as already imported."""
    previous, current = dataset.months[-2], dataset.months[-1]
    return statement_csv((*previous.movements[-DOWNLOAD_OVERLAP:], *current.movements))


def download_receivables(dataset: Dataset) -> bytes:
    return receivables_csv(dataset.months[-1].receivables)
