from dataclasses import dataclass, fields

BASIS_POINTS = 10_000
MAX_TOLERANCE_MIN_CENTS = 1_000_000
MAX_DETRACTION_RATES = 5


class InvalidSettingsError(ValueError):
    pass


@dataclass(frozen=True)
class OrganizationSettings:
    name: str
    tolerance_min_cents: int
    tolerance_bp: int
    detraction_rates_bp: tuple[int, ...]

    def __post_init__(self) -> None:
        rates = self.detraction_rates_bp
        if (
            not self.name.strip()
            or not 0 <= self.tolerance_min_cents <= MAX_TOLERANCE_MIN_CENTS
            or not 0 <= self.tolerance_bp <= BASIS_POINTS
            or len(rates) > MAX_DETRACTION_RATES
            or len(set(rates)) != len(rates)
            or any(not 0 < rate <= BASIS_POINTS for rate in rates)
        ):
            raise InvalidSettingsError

    def normalized(self) -> OrganizationSettings:
        return OrganizationSettings(
            self.name.strip(),
            self.tolerance_min_cents,
            self.tolerance_bp,
            tuple(sorted(self.detraction_rates_bp)),
        )

    def changed_fields(self, other: OrganizationSettings) -> list[str]:
        return [
            field.name
            for field in fields(self)
            if getattr(self, field.name) != getattr(other, field.name)
        ]
