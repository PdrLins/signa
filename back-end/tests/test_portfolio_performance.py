"""5Y/ALL history thinned to weekly points."""

def test_thin_weekly_keeps_ends_and_one_point_per_week():
    from datetime import date, timedelta
    from app.services.portfolio_performance import thin_weekly
    start = date(2021, 1, 4)
    pts = [(start + timedelta(days=i), 100.0 + i) for i in range(0, 1800) if (start + timedelta(days=i)).weekday() < 5]
    out = thin_weekly(pts)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    weeks = [t.isocalendar()[:2] for t, _ in out[1:-1]]
    assert len(weeks) == len(set(weeks))
    assert all(t.weekday() == 4 for t, _ in out[1:-1])   # each week's Friday
    assert thin_weekly(pts[:50]) == pts[:50]
