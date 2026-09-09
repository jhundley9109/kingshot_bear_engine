from collections import defaultdict
from datetime import datetime
from io import BytesIO
import math


def create_player_trend_chart(rows, months, searched_name=None):
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

    title_name = searched_name or "Player"
    axis.set_title(f"{title_name} Bear Trap damage - last {months} month(s)")
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


def _compact_damage(value):
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:,.0f}"


def build_event_trend_data(rows):
    labels = []
    damage = []
    participants = []
    rallies = []

    for row in rows:
        event_date = datetime.fromisoformat(row["event_date"])
        labels.append(f"{event_date:%b %d}\nEvent {row['event_id']}")
        damage.append(row["alliance_damage"])
        participants.append(row["participant_count"])
        rallies.append(row["rallies"])

    return {
        "labels": labels,
        "damage": damage,
        "participants": participants,
        "rallies": rallies,
    }


def create_event_trend_chart(rows, months):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    trend = build_event_trend_data(rows)
    positions = list(range(len(rows)))
    chart_width = max(10, min(18, len(rows) * 1.1))
    figure, axes = plt.subplots(3, 1, figsize=(chart_width, 10), sharex=True)
    series = (
        (
            "Total damage",
            trend["damage"],
            "#f4a261",
            _compact_damage,
        ),
        (
            "Participants",
            trend["participants"],
            "#90be6d",
            lambda value: f"{value:,.0f}",
        ),
        (
            "Total rallies",
            trend["rallies"],
            "#8ecae6",
            lambda value: f"{value:,.0f}",
        ),
    )
    for axis, (label, raw_values, color, value_formatter) in zip(axes, series):
        values = [float("nan") if value is None else value for value in raw_values]
        present_values = [value for value in values if not math.isnan(value)]
        annotation_baseline = min(present_values) if present_values else 0
        axis.plot(positions, values, marker="o", linewidth=2, color=color)
        axis.set_ylabel(label)
        axis.grid(alpha=0.25)
        axis.margins(y=0.18)
        for position, value in zip(positions, values):
            display_value = "N/A" if math.isnan(value) else value_formatter(value)
            annotation_y = annotation_baseline if math.isnan(value) else value
            axis.annotate(
                display_value,
                (position, annotation_y),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                fontsize=8,
            )

    axes[0].yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: _compact_damage(value))
    )
    axes[1].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[2].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[0].set_title(f"Bear Trap event comparison — last {months} month(s)")
    axes[2].set_xlabel("Event date and ID")
    axes[2].set_xticks(positions, trend["labels"])
    figure.tight_layout()
    output = BytesIO()
    figure.savefig(output, format="png", dpi=160)
    plt.close(figure)
    output.seek(0)
    return output
