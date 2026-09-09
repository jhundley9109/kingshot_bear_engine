import discord

from commands.support import log_discord_request
from services.troop_calculator import (
    calculate_bear_deployment,
    troop_count_value,
    troop_ratio_value,
)
from views.command_forms import TextField, command_form


def _ratio_text(ratio):
    return " / ".join(str(value) for value in ratio)


def _calculator_embed(interaction, calculation):
    lead = calculation["lead"]
    embed = discord.Embed(
        title="🐻 Kingshot Bear Troop Calculator",
        description=(
            f"Results for {interaction.user.mention}\n"
            "Ratio order: **Infantry / Cavalry / Archers**"
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Lead march",
        value=(
            f"Ratio: **{_ratio_text(lead['ratio'])}**\n"
            f"Infantry: **{lead['infantry']:,}** · "
            f"Cavalry: **{lead['cavalry']:,}** · "
            f"Archers: **{lead['archers']:,}**\n"
            f"Total: **{lead['total']:,}**"
        ),
        inline=False,
    )

    for option in calculation["options"]:
        value = (
            f"Recommended ratio: **{_ratio_text(option['ratio'])}**\n"
            f"Deployable: **{option['total_used']:,} / "
            f"{option['total_capacity']:,}** troops"
        )
        if not option["minimum_met"]:
            troop_names = ", ".join(
                troop_type.title() for troop_type in option["missing_minimums"]
            )
            value += (
                f"\n⚠️ Cannot maintain the 1% minimum for: **{troop_names}**"
            )
        if not option["full"]:
            value += f"\n⚠️ Short **{option['shortage']:,}** troops"
        else:
            value += "\n✅ All joiner marches can be filled"

        embed.add_field(
            name=f"{option['joiner_count']} joiners",
            value=value,
            inline=False,
        )

    embed.set_footer(
        text=(
            "Joiners reserve at least 1% of each troop type per march, then "
            "prioritize Archers → Cavalry → Infantry."
        )
    )
    return embed


def register_calculator_command(group, log_event):
    @group.command(
        name="calculator",
        description="Calculate lead and joiner troop deployments",
    )
    @log_discord_request(log_event, "/bear calculator")
    @command_form(
        "Bear troop calculator",
        fields=(
            TextField(
                name="infantry",
                label="Total Infantry",
                placeholder="Example: 350,000",
                required=True,
                parser=troop_count_value("Infantry"),
            ),
            TextField(
                name="cavalry",
                label="Total Cavalry",
                placeholder="Example: 320,000",
                required=True,
                parser=troop_count_value("Cavalry"),
            ),
            TextField(
                name="archers",
                label="Total Archers",
                placeholder="Example: 400,000",
                required=True,
                parser=troop_count_value("Archers"),
            ),
            TextField(
                name="march_capacity",
                label="March Capacity",
                placeholder="Example: 134,710",
                required=True,
                parser=troop_count_value("March capacity", minimum=3),
            ),
            TextField(
                name="lead_ratio",
                label="Lead Ratio — Infantry/Cavalry/Archers",
                placeholder="Example: 1/9/90",
                required=True,
                parser=troop_ratio_value,
            ),
        ),
    )
    async def calculator(
        interaction,
        infantry,
        cavalry,
        archers,
        march_capacity,
        lead_ratio,
    ):
        calculation = calculate_bear_deployment(
            infantry,
            cavalry,
            archers,
            march_capacity,
            lead_ratio,
        )
        await interaction.response.send_message(
            embed=_calculator_embed(interaction, calculation)
        )
