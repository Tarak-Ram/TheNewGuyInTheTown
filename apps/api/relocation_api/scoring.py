"""Area ranking maths. Pure functions: no database, no network, no model.

score = 0.45 x commute + 0.30 x budget_fit + 0.15 x confirmed_supply + 0.10 x preference
(the formula in docs/PRD.md; tune the weights from pilot feedback).
"""

from dataclasses import dataclass

W_COMMUTE = 0.45
W_BUDGET = 0.30
W_SUPPLY = 0.15
W_PREFERENCE = 0.10

GOOD_COMMUTE_MIN = 15  # at or under this, the commute scores 1.0
BAD_COMMUTE_MIN = 75  # at or over this, the commute scores 0.0

# We do not yet store food or gender details per PG, so preference cannot separate areas.
# A neutral 0.5 keeps it from moving the ranking until that data exists.
NEUTRAL_PREFERENCE = 0.5


def clamp(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def commute_score(minutes: int) -> float:
    return clamp((BAD_COMMUTE_MIN - minutes) / (BAD_COMMUTE_MIN - GOOD_COMMUTE_MIN))


def budget_fit_score(rent_min: int, rent_max: int, budget_max: int) -> float:
    """Share of the area's rent range that is within budget. Cheaper than budget is fine."""
    if rent_max <= rent_min:
        return 1.0 if rent_min <= budget_max else 0.0
    return clamp((budget_max - rent_min) / (rent_max - rent_min))


def budget_gap(rent_min: int, budget_max: int) -> int:
    """How much more monthly budget the cheapest option here needs (0 if it already fits)."""
    return max(0, rent_min - budget_max)


def supply_score(consented_pgs: int, max_consented_pgs: int) -> float:
    return consented_pgs / max_consented_pgs if max_consented_pgs > 0 else 0.0


@dataclass(frozen=True)
class AreaInput:
    area_id: str
    name: str
    commute_minutes: int
    rent_min: int
    rent_max: int
    consented_pgs: int


@dataclass(frozen=True)
class ScoredArea:
    area: AreaInput
    score: float
    components: dict[str, float]
    budget_gap: int


def score_areas(areas: list[AreaInput], budget_max: int) -> list[ScoredArea]:
    """Score every area and return them best first. Ties break on shorter commute, then name."""
    max_pgs = max((a.consented_pgs for a in areas), default=0)
    scored = []
    for a in areas:
        components = {
            "commute": commute_score(a.commute_minutes),
            "budget_fit": budget_fit_score(a.rent_min, a.rent_max, budget_max),
            "confirmed_supply": supply_score(a.consented_pgs, max_pgs),
            "preference": NEUTRAL_PREFERENCE,
        }
        total = (
            W_COMMUTE * components["commute"]
            + W_BUDGET * components["budget_fit"]
            + W_SUPPLY * components["confirmed_supply"]
            + W_PREFERENCE * components["preference"]
        )
        scored.append(
            ScoredArea(a, round(total, 4), components, budget_gap(a.rent_min, budget_max))
        )
    return sorted(scored, key=lambda s: (-s.score, s.area.commute_minutes, s.area.name))


def top_areas(scored: list[ScoredArea], limit: int = 5) -> list[ScoredArea]:
    return scored[:limit]
