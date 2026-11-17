def render_daily_bar_chart(daily_totals: list[dict], width: int = 480, height: int = 120) -> str:
    if not daily_totals:
        return f'<svg width="{width}" height="{height}" role="img"></svg>'

    max_tokens = max(row["tokens"] for row in daily_totals) or 1
    plot_height = height - 20
    bar_width = width / len(daily_totals)

    bars = []
    for i, row in enumerate(daily_totals):
        bar_height = (row["tokens"] / max_tokens) * plot_height
        x = i * bar_width
        y = height - bar_height
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.8:.1f}" '
            f'height="{bar_height:.1f}" fill="#4f7cff">'
            f'<title>{row["day"]}: {row["tokens"]} tokens</title></rect>'
        )

    return f'<svg width="{width}" height="{height}" role="img">' + "".join(bars) + "</svg>"
