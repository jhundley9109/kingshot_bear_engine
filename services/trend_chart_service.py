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


def create_event_trend_chart(rows, months):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    dates = [datetime.fromisoformat(f"{row['event_date']}T{row['event_time'] or '00:00:00'}") for row in rows]
    rallies = [row['rallies'] or 0 for row in rows]
    participants = [row['participant_count'] for row in rows]
    damage = [row['alliance_damage'] or 0 for row in rows]

    figure, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
    series = [("Rallies", rallies, "#8ecae6"), ("Participants", participants, "#90be6d"), ("Alliance damage", damage, "#f4a261")]
    for axis, (label, values, color) in zip(axes, series):
        axis.plot(dates, values, marker="o", linewidth=2, color=color)
        axis.set_ylabel(label)
        axis.grid(alpha=0.25)
    axes[2].yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1_000_000:.0f}M"))
    axes[0].set_title(f"Bear Trap event trends — last {months} month(s)")
    axes[2].set_xlabel("Event date")
    figure.autofmt_xdate()
    figure.tight_layout()
    output = BytesIO()
    figure.savefig(output, format="png", dpi=160)
    plt.close(figure)
    output.seek(0)
    return output
