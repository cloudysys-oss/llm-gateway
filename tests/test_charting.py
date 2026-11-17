from app.charting import render_daily_bar_chart


def test_empty_data_returns_empty_svg():
    svg = render_daily_bar_chart([])

    assert svg.startswith("<svg")
    assert "<rect" not in svg


def test_renders_one_rect_per_day():
    data = [
        {"day": "2026-07-29", "tokens": 100},
        {"day": "2026-07-30", "tokens": 50},
    ]

    svg = render_daily_bar_chart(data)

    assert svg.count("<rect") == 2
    assert "2026-07-29" in svg
    assert "100 tokens" in svg


def test_tallest_bar_uses_full_available_height():
    data = [{"day": "2026-07-30", "tokens": 100}]

    svg = render_daily_bar_chart(data, width=480, height=120)

    assert 'height="100.0"' in svg
