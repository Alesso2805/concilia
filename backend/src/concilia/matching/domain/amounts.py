from concilia.matching.domain.model import EnginePolicy

BASIS_POINTS = 10_000
CENTS_PER_SOL = 100
DETRACTION_MATCH_CENTS = 100


def tolerance_cents(balance_cents: int, policy: EnginePolicy) -> int:
    return max(policy.tolerance_min_cents, balance_cents * policy.tolerance_bp // BASIS_POINTS)


def within_tolerance(difference_cents: int, balance_cents: int, policy: EnginePolicy) -> bool:
    return abs(difference_cents) <= tolerance_cents(balance_cents, policy)


def detraction_cents(balance_cents: int, rate_bp: int) -> int:
    half_sol = BASIS_POINTS * CENTS_PER_SOL // 2
    soles = (balance_cents * rate_bp + half_sol) // (BASIS_POINTS * CENTS_PER_SOL)
    return soles * CENTS_PER_SOL


def detraction_rate(amount_cents: int, balance_cents: int, policy: EnginePolicy) -> int | None:
    residuals = {
        rate: abs(amount_cents - (balance_cents - detraction_cents(balance_cents, rate)))
        for rate in policy.detraction_rates_bp
    }
    matching = [rate for rate, residual in residuals.items() if residual <= DETRACTION_MATCH_CENTS]
    return min(matching, key=lambda rate: (residuals[rate], rate), default=None)
