import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from concilia.shared.kernel.normalization import normalize_text

DATASET_VERSION = 1
MONTHS = (date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1))
IMPORTED_MONTHS = 2

# Two distinctive words per customer and no word shared between customers, so the engine's
# fuzzy customer rules (R4 to R6) never tie between two of them.
CUSTOMERS = (
    ("Textiles Paracas SAC", "20512345671"),
    ("Agroindustrias Huallaga SAC", "20498765432"),
    ("Distribuidora Chavin SRL", None),
    ("Ferreteria Amaru EIRL", "20601234567"),
    ("Constructora Titicaca SA", "20434567890"),
    ("Panificadora Sumaq SAC", None),
    ("Importaciones Kuntur SAC", "20587654321"),
    ("Laboratorios Mantaro SA", "20123456789"),
    ("Transportes Colca SRL", None),
    ("Comercializadora Vilcanota SAC", "20345678901"),
    ("Grafica Nazca EIRL", None),
    ("Muebleria Chachapoyas SAC", "20456789012"),
    ("Pesquera Paita SA", "20567890123"),
    ("Clinica Arequipeña SAC", "20678901234"),
    ("Libreria Quillabamba SRL", None),
    ("Avicola Chancay SAC", "20789012345"),
    ("Metalmecanica Ilo SAC", "20890123456"),
    ("Consultora Yanahuara SAC", None),
    ("Plasticos Huaral SA", "20901234567"),
    ("Vidrieria Moquegua EIRL", None),
    ("Cafetalera Pichanaki SAC", "20112233445"),
    ("Embotelladora Tumbes SA", "20223344556"),
    ("Calzados Trujillanos SAC", "20334455667"),
    ("Joyeria Catacaos SRL", None),
    ("Electricos Huancayo SAC", "20445566778"),
    ("Hospedaje Ollantaytambo EIRL", None),
    ("Agricola Majes SAC", "20556677889"),
    ("Inmobiliaria Miraflores SA", "20667788990"),
    ("Cerámicos Lurin SAC", "20778899001"),
    ("Servicios Pachacamac SRL", None),
)
UNRELATED = (
    "INTERESES GANADOS",
    "DEVOLUCION SUNAT",
    "TRANSF ENTRE CUENTAS PROPIAS",
    "ABONO POR IDENTIFICAR",
)
SUPPLIERS = ("ENERGIA DEL SUR", "LOGISTICA ANDES", "PAPELERA LIMA", "SEGUROS RIMAC")


class Case(StrEnum):
    EXACT = "exact"
    SEVERAL_DOCUMENTS = "several_documents"
    ROUNDING = "rounding"
    DETRACTION = "detraction"
    SAME_CUSTOMER = "same_customer"
    PAID_IN_PARTS = "paid_in_parts"
    AMOUNT_AND_DATE = "amount_and_date"
    AMBIGUOUS = "ambiguous"
    PARTIAL = "partial"
    REPEATED = "repeated"
    UNRELATED = "unrelated"
    DEBIT = "debit"


ENGINE_CASES = frozenset(
    {
        Case.EXACT,
        Case.SEVERAL_DOCUMENTS,
        Case.ROUNDING,
        Case.DETRACTION,
        Case.SAME_CUSTOMER,
        Case.PAID_IN_PARTS,
        Case.AMOUNT_AND_DATE,
    }
)
CASES_PER_MONTH = {
    Case.EXACT: 68,
    Case.SEVERAL_DOCUMENTS: 6,
    Case.ROUNDING: 5,
    Case.DETRACTION: 5,
    Case.SAME_CUSTOMER: 6,
    Case.PAID_IN_PARTS: 3,
    Case.AMOUNT_AND_DATE: 10,
    Case.AMBIGUOUS: 3,
    Case.PARTIAL: 3,
}
UNPAID_PER_MONTH = 8
DEBITS_PER_MONTH = 47


@dataclass(frozen=True)
class DemoReceivable:
    customer_name: str
    customer_tax_id: str | None
    doc_number: str
    issued_on: date
    due_on: date
    amount_cents: int


@dataclass(frozen=True)
class DemoMovement:
    booked_on: date
    description: str
    operation_number: str
    amount_cents: int
    case: Case
    pays: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemoMonth:
    period: date
    movements: tuple[DemoMovement, ...]
    receivables: tuple[DemoReceivable, ...]


@dataclass(frozen=True)
class Dataset:
    version: int
    months: tuple[DemoMonth, ...]


def detraction_cents(amount_cents: int, rate_bp: int) -> int:
    """SUNAT detraction: the rate applied to the amount, rounded half up to whole soles."""
    return (amount_cents * rate_bp + 500_000) // 1_000_000 * 100


@dataclass
class _Builder:
    rng: random.Random
    period: date
    next_document: int
    amounts: set[int]
    receivables: list[DemoReceivable] = field(default_factory=list)
    movements: list[DemoMovement] = field(default_factory=list)
    operations: set[str] = field(default_factory=set)

    def day(self, first: int, last: int) -> date:
        return self.period + timedelta(days=self.rng.randint(first, last) - 1)

    def amount(self, low: int = 50_00, high: int = 9_000_00) -> int:
        while True:
            value = self.rng.randrange(low, high)
            if value not in self.amounts:
                self.amounts.add(value)
                return value

    def operation(self) -> str:
        while True:
            value = str(self.rng.randrange(10**6, 10**8))
            if value not in self.operations:
                self.operations.add(value)
                return value

    def invoice(
        self, customer: tuple[str, str | None], amount: int | None = None
    ) -> DemoReceivable:
        issued_on = self.day(1, 18)
        number = self.next_document
        self.next_document += 1
        receivable = DemoReceivable(
            customer_name=customer[0],
            customer_tax_id=customer[1],
            doc_number=f"F001-{number:08d}",
            issued_on=issued_on,
            due_on=issued_on + timedelta(days=self.rng.choice((15, 30, 30, 45))),
            amount_cents=amount if amount is not None else self.amount(),
        )
        self.receivables.append(receivable)
        return receivable

    def credit(
        self,
        booked_on: date,
        description: str,
        amount: int,
        case: Case,
        *pays: DemoReceivable,
        operation: str | None = None,
    ) -> None:
        self.movements.append(
            DemoMovement(
                booked_on,
                description,
                operation or self.operation(),
                amount,
                case,
                tuple(_short(receivable) for receivable in pays),
            )
        )

    def paid_on(self, *receivables: DemoReceivable) -> date:
        latest = max(receivable.issued_on for receivable in receivables)
        month_end = (self.period + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return min(latest + timedelta(days=self.rng.randint(1, 10)), month_end)


def _short(receivable: DemoReceivable) -> str:
    series, number = receivable.doc_number.split("-")
    return f"{series}-{int(number)}"


def _customer_words(name: str) -> str:
    return " ".join(normalize_text(name).split()[:2])


def _month(builder: _Builder) -> None:
    rng = builder.rng

    def customer() -> tuple[str, str | None]:
        return rng.choice(CUSTOMERS)

    for _ in range(CASES_PER_MONTH[Case.EXACT]):
        receivable = builder.invoice(customer())
        reference = rng.choice(
            (receivable.doc_number, _short(receivable), _short(receivable).replace("F001", "F1"))
        )
        template = rng.choice(("PAGO FACT {}", "ABONO {} {}", "TRANSF {} {}", "DEP {}"))
        description = template.format(reference, _customer_words(receivable.customer_name))
        builder.credit(
            builder.paid_on(receivable),
            description,
            receivable.amount_cents,
            Case.EXACT,
            receivable,
        )
    for _ in range(CASES_PER_MONTH[Case.SEVERAL_DOCUMENTS]):
        pair = [builder.invoice(customer()) for _ in range(2)]
        description = "PAGO " + " ".join(_short(receivable) for receivable in pair)
        total = sum(receivable.amount_cents for receivable in pair)
        builder.amounts.add(total)
        builder.credit(builder.paid_on(*pair), description, total, Case.SEVERAL_DOCUMENTS, *pair)
    for _ in range(CASES_PER_MONTH[Case.ROUNDING]):
        receivable = builder.invoice(customer())
        paid = receivable.amount_cents - rng.randint(1, 99)
        builder.credit(
            builder.paid_on(receivable),
            f"PAGO FACT {_short(receivable)}",
            paid,
            Case.ROUNDING,
            receivable,
        )
    for _ in range(CASES_PER_MONTH[Case.DETRACTION]):
        receivable = builder.invoice(customer(), builder.amount(1_000_00, 20_000_00))
        rate = rng.choice((1000, 1200))
        paid = receivable.amount_cents - detraction_cents(receivable.amount_cents, rate)
        builder.credit(
            builder.paid_on(receivable),
            f"PAGO {_short(receivable)} NETO DETRACCION",
            paid,
            Case.DETRACTION,
            receivable,
        )
    for client in rng.sample(CUSTOMERS, CASES_PER_MONTH[Case.SAME_CUSTOMER]):
        pair = [builder.invoice(client) for _ in range(2)]
        total = sum(receivable.amount_cents for receivable in pair)
        builder.amounts.add(total)
        builder.credit(
            builder.paid_on(*pair),
            f"TRANSF {_customer_words(client[0])}",
            total,
            Case.SAME_CUSTOMER,
            *pair,
        )
    for client in rng.sample(CUSTOMERS, CASES_PER_MONTH[Case.PAID_IN_PARTS]):
        receivable = builder.invoice(client)
        first = rng.randrange(receivable.amount_cents // 3, 2 * receivable.amount_cents // 3)
        for part in (first, receivable.amount_cents - first):
            builder.amounts.add(part)
            builder.credit(
                builder.paid_on(receivable),
                f"ABONO PARCIAL {_customer_words(client[0])}",
                part,
                Case.PAID_IN_PARTS,
                receivable,
            )
    for _ in range(CASES_PER_MONTH[Case.AMOUNT_AND_DATE]):
        receivable = builder.invoice(customer())
        builder.credit(
            builder.paid_on(receivable),
            rng.choice(("DEPOSITO EN EFECTIVO", "ABONO EN CUENTA", "TRANSF INTERBANCARIA")),
            receivable.amount_cents,
            Case.AMOUNT_AND_DATE,
            receivable,
        )
    for _ in range(CASES_PER_MONTH[Case.AMBIGUOUS]):
        amount = builder.amount()
        twins = [builder.invoice(customer(), amount) for _ in range(2)]
        builder.credit(
            builder.paid_on(*twins), "DEPOSITO EN EFECTIVO", amount, Case.AMBIGUOUS, twins[0]
        )
    for _ in range(CASES_PER_MONTH[Case.PARTIAL]):
        receivable = builder.invoice(customer())
        paid = receivable.amount_cents * rng.randint(30, 60) // 100
        builder.amounts.add(paid)
        builder.credit(
            builder.paid_on(receivable),
            f"PAGO A CUENTA {_short(receivable)}",
            paid,
            Case.PARTIAL,
            receivable,
        )
    for _ in range(UNPAID_PER_MONTH):
        builder.invoice(customer())
    repeated_on, repeated_amount = builder.day(5, 25), builder.amount(20_00, 500_00)
    repeated_operation = builder.operation()
    for _ in range(2):
        builder.credit(
            repeated_on,
            "ABONO POR REGULARIZAR",
            repeated_amount,
            Case.REPEATED,
            operation=repeated_operation,
        )
    for description in UNRELATED:
        builder.credit(
            builder.day(1, 28), description, builder.amount(10_00, 900_00), Case.UNRELATED
        )
    for _ in range(DEBITS_PER_MONTH):
        description = rng.choice(
            (
                "COMISION MANTENIMIENTO",
                "ITF",
                f"PAGO PROVEEDOR {rng.choice(SUPPLIERS)}",
                "PAGO HABERES",
                "PAGO IMPUESTOS SUNAT",
            )
        )
        builder.movements.append(
            DemoMovement(
                builder.day(1, 28),
                description,
                builder.operation(),
                -builder.amount(5_00, 8_000_00),
                Case.DEBIT,
            )
        )


def _ordered(movements: list[DemoMovement]) -> Iterator[DemoMovement]:
    return iter(
        sorted(movements, key=lambda movement: (movement.booked_on, movement.operation_number))
    )


def build_dataset() -> Dataset:
    rng = random.Random(f"concilia-demo-{DATASET_VERSION}")  # noqa: S311 - fictional data, not secrets
    amounts: set[int] = set()
    next_document = 1
    months = []
    for period in MONTHS:
        builder = _Builder(rng, period, next_document, amounts)
        _month(builder)
        next_document = builder.next_document
        months.append(
            DemoMonth(
                period,
                tuple(_ordered(builder.movements)),
                tuple(sorted(builder.receivables, key=lambda r: r.doc_number)),
            )
        )
    return Dataset(DATASET_VERSION, tuple(months))
