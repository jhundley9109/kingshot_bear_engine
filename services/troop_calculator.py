import math


def troop_count_value(label, minimum=0):
    def parse(value):
        normalized = value.replace(",", "").strip()

        try:
            result = int(normalized)
        except ValueError as error:
            raise ValueError(
                f"{label} must be a whole number, "
                f"such as 350000 or 350,000."
            ) from error

        if result < minimum:
            requirement = (
                "greater than 0"
                if minimum == 1
                else f"at least {minimum}"
            )
            raise ValueError(
                f"{label} must be {requirement}."
            )

        return result

    return parse


def troop_ratio_value(value):
    try:
        ratio = tuple(
            int(part)
            for part in value.replace(" ", "").split("/")
        )
    except ValueError as error:
        raise ValueError(
            "Lead ratio must use Infantry/Cavalry/Archers, "
            "such as 1/9/90."
        ) from error

    if len(ratio) != 3:
        raise ValueError(
            "Lead ratio must use Infantry/Cavalry/Archers, "
            "such as 1/9/90."
        )

    if any(percent < 0 for percent in ratio):
        raise ValueError(
            "Lead ratio percentages cannot be negative."
        )

    if sum(ratio) != 100:
        raise ValueError(
            f"Lead ratio must total 100%; "
            f"{ratio[0]}/{ratio[1]}/{ratio[2]} "
            f"totals {sum(ratio)}%."
        )

    return ratio


def _lead_march(march_capacity, lead_ratio):
    infantry = round(
        march_capacity * lead_ratio[0] / 100
    )
    cavalry = round(
        march_capacity * lead_ratio[1] / 100
    )

    archers = (
        march_capacity
        - infantry
        - cavalry
    )

    return {
        "infantry": infantry,
        "cavalry": cavalry,
        "archers": archers,
        "total": march_capacity,
        "ratio": lead_ratio,
    }


def _joiner_option(
    joiner_count,
    joiner_capacity,
    available,
):
    total_capacity = (
        joiner_capacity * joiner_count
    )

    minimum_per_march = math.ceil(
        joiner_capacity * 0.01
    )

    # Because every joiner must use the same formation,
    # determine how many of each troop type can safely
    # be assigned to every march.
    available_per_march = {
        troop_type: (
            available[troop_type] // joiner_count
        )
        for troop_type in (
            "infantry",
            "cavalry",
            "archers",
        )
    }

    missing_minimums = [
        troop_type
        for troop_type in (
            "infantry",
            "cavalry",
            "archers",
        )
        if (
            available_per_march[troop_type]
            < minimum_per_march
        )
    ]

    # Reserve at least 1% of every troop type first.
    per_march = {
        troop_type: min(
            available_per_march[troop_type],
            minimum_per_march,
        )
        for troop_type in (
            "infantry",
            "cavalry",
            "archers",
        )
    }

    space_left = (
        joiner_capacity
        - sum(per_march.values())
    )

    # Fill remaining space in priority order:
    # Archers → Cavalry → Infantry.
    for troop_type in (
        "archers",
        "cavalry",
        "infantry",
    ):
        extra_available = (
            available_per_march[troop_type]
            - per_march[troop_type]
        )

        extra = min(
            extra_available,
            space_left,
        )

        per_march[troop_type] += extra
        space_left -= extra

    total_per_march = sum(
        per_march.values()
    )

    total_used = (
        total_per_march * joiner_count
    )

    if total_per_march:
        infantry_percent = round(
            per_march["infantry"]
            / total_per_march
            * 100
        )

        cavalry_percent = round(
            per_march["cavalry"]
            / total_per_march
            * 100
        )

        archer_percent = (
            100
            - infantry_percent
            - cavalry_percent
        )
    else:
        infantry_percent = 0
        cavalry_percent = 0
        archer_percent = 0

    used = {
        troop_type: (
            per_march[troop_type]
            * joiner_count
        )
        for troop_type in (
            "infantry",
            "cavalry",
            "archers",
        )
    }

    return {
        "joiner_count": joiner_count,
        "joiner_capacity": joiner_capacity,
        "total_capacity": total_capacity,
        "total_used": total_used,
        "shortage": (
            total_capacity - total_used
        ),
        "full": (
            total_used == total_capacity
        ),
        "minimum_per_march": minimum_per_march,
        "minimum_met": not missing_minimums,
        "missing_minimums": missing_minimums,
        "used": used,
        "per_march": per_march,
        "ratio": (
            infantry_percent,
            cavalry_percent,
            archer_percent,
        ),
    }


def calculate_bear_deployment(
    infantry,
    cavalry,
    archers,
    march_capacity,
    lead_ratio,
    joiner_capacity=None,
    joiner_counts=range(2, 7),
):
    troops = {
        "infantry": infantry,
        "cavalry": cavalry,
        "archers": archers,
    }

    if any(
        value < 0
        for value in troops.values()
    ):
        raise ValueError(
            "Troop counts cannot be negative."
        )

    if march_capacity < 3:
        raise ValueError(
            "March capacity must be at least 3."
        )

    # If no separate troop limit is supplied,
    # joiners use normal march capacity.
    if joiner_capacity is None:
        joiner_capacity = march_capacity

    if joiner_capacity < 3:
        raise ValueError(
            "Joiner capacity must be at least 3."
        )

    if (
        len(lead_ratio) != 3
        or any(
            value < 0
            for value in lead_ratio
        )
    ):
        raise ValueError(
            "Lead ratio must contain three "
            "non-negative percentages."
        )

    if sum(lead_ratio) != 100:
        raise ValueError(
            "Lead ratio must total 100%."
        )

    # The lead ALWAYS uses normal march capacity,
    # even when joiners are subject to a troop limit.
    lead = _lead_march(
        march_capacity,
        lead_ratio,
    )

    shortages = {
        troop_type: (
            lead[troop_type]
            - troops[troop_type]
        )
        for troop_type in troops
        if (
            lead[troop_type]
            > troops[troop_type]
        )
    }

    if shortages:
        details = ", ".join(
            f"{troop_type.title()} needs "
            f"{lead[troop_type]:,} "
            f"(have {troops[troop_type]:,})"
            for troop_type in shortages
        )

        raise ValueError(
            f"Not enough troops for the "
            f"lead march: {details}."
        )

    # Lead troops are removed before calculating joiners.
    remaining = {
        troop_type: (
            troops[troop_type]
            - lead[troop_type]
        )
        for troop_type in troops
    }

    options = [
        _joiner_option(
            count,
            joiner_capacity,
            remaining,
        )
        for count in joiner_counts
    ]

    return {
        "lead": lead,
        "remaining": remaining,
        "joiner_capacity": joiner_capacity,
        "options": options,
    }