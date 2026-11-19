"""AC-01: 날짜 조합 생성."""
from datetime import date


def test_all_combos_count_and_constraints(cfg):
    combos = cfg.all_combos(date(2026, 11, 19))
    assert len(combos) == 64
    assert len(set(combos)) == 64
    for c in combos:
        assert 3 <= c.nights <= 7
        assert date(2026, 12, 17) <= c.depart <= date(2026, 12, 30)
        assert c.return_date <= date(2027, 1, 3)


def test_representative_combos_are_subset(cfg):
    reps = cfg.representative_combos(date(2026, 11, 19))
    assert len(reps) == 6
    assert set(reps) <= set(cfg.all_combos(date(2026, 11, 19)))


def test_departures_on_or_before_run_date_are_excluded(cfg):
    today = date(2026, 12, 20)
    combos = cfg.all_combos(today)
    assert combos and all(c.depart > today for c in combos)
    # 12/17, 12/18 출발 대표 조합은 제외된다
    assert [c.depart for c in cfg.representative_combos(today)] == [
        date(2026, 12, 21), date(2026, 12, 23), date(2026, 12, 27), date(2026, 12, 29)
    ]
    assert cfg.all_combos(date(2026, 12, 30)) == []


def test_destinations_config(cfg):
    assert len(cfg.destinations) == 60
    domestic = [d for d in cfg.destinations if d.is_domestic]
    assert [(d.origin, d.code) for d in domestic] == [("GMP", "CJU")]
    assert {d.origin for d in cfg.destinations} == {"ICN", "GMP"}
