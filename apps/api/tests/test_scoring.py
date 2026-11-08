from relocation_api.scoring import (
    AreaInput,
    budget_fit_score,
    budget_gap,
    commute_score,
    score_areas,
    supply_score,
)


def area(name, minutes, rent_min=8000, rent_max=14000, pgs=2):
    return AreaInput(name.lower(), name, minutes, rent_min, rent_max, pgs)


def test_commute_score_bounds():
    assert commute_score(10) == 1.0
    assert commute_score(15) == 1.0
    assert commute_score(75) == 0.0
    assert commute_score(120) == 0.0
    assert 0 < commute_score(45) < 1


def test_budget_fit():
    assert budget_fit_score(8000, 14000, 14000) == 1.0  # whole range fits
    assert budget_fit_score(8000, 14000, 20000) == 1.0  # budget above the range
    assert budget_fit_score(8000, 14000, 8000) == 0.0  # only the very bottom fits
    assert round(budget_fit_score(9000, 16000, 14000), 3) == round(5 / 7, 3)
    assert budget_fit_score(12000, 16000, 9000) == 0.0


def test_budget_gap_is_zero_when_it_fits():
    assert budget_gap(8000, 14000) == 0
    assert budget_gap(12000, 9000) == 3000


def test_supply_score():
    assert supply_score(2, 4) == 0.5
    assert supply_score(0, 0) == 0.0


def test_prd_example_close_area_beats_cheap_far_area():
    kondapur = area("Kondapur", 25, 8000, 14000)  # fits budget
    far_cheap = area("FarCheap", 70, 4000, 7000)  # cheaper, but 70 minutes away
    ranked = score_areas([far_cheap, kondapur], budget_max=14000)
    assert [r.area.name for r in ranked] == ["Kondapur", "FarCheap"]


def test_score_uses_the_prd_weights():
    [r] = score_areas([area("A", 15, 8000, 14000, pgs=3)], budget_max=14000)
    # 0.45*1 + 0.30*1 + 0.15*1 + 0.10*0.5
    assert r.score == 0.95


def test_ties_break_on_shorter_commute_then_name():
    same = [area("B", 20), area("A", 20)]
    assert [r.area.name for r in score_areas(same, 14000)] == ["A", "B"]
