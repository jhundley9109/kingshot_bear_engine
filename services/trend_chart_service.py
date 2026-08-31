from collections import defaultdict
from datetime import datetime
from io import BytesIO


def create_player_trend_chart(rows, months):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    series = defaultdict(list)
    for row in rows:
        event_time = row["event_time"] or "00:00:00"
        timestamp = datetime.fromisoformat(f"{row['event_date']}T{event_time}")
        series[row["player_name"]].append((timestamp, row["damage"]))

    figure, axis = plt.subplots(figsize=(10, 5))
    for player_name, points in series.items():
        dates, damage = zip(*points)
        axis.plot(dates, damage, marker="o", linewidth=2, label=player_name)

    axis.set_title(f"Bear Trap damage — last {months} month(s)")
    axis.set_xlabel("Event date")
    axis.set_ylabel("Damage")
    axis.grid(alpha=0.25)
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1_000_000:.0f}M"))
    if len(series) > 1:
        axis.legend()
    figure.autofmt_xdate()
    figure.tight_layout()

    output = BytesIO()
    figure.savefig(output, format="png", dpi=160)
    plt.close(figure)
    output.seek(0)
    return output
