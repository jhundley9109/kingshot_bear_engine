import discord

from commands.support import log_discord_request
from services.troop_calculator import (
    calculate_bear_deployment,
    troop_count_value,
    troop_ratio_value,
)
from views.command_forms import CommandFormModal, TextField


def _ratio_text(ratio):
    return " / ".join(str(value) for value in ratio)


def _per_march_text(option):
    return "\n".join(
        f"{troop_type.title()}: "
        f"**{option['per_march'][troop_type]:,}**"
        for troop_type in ("infantry", "cavalry", "archers")
    )


def _joiner_counts(joiner_choice):
    if joiner_choice == "all":
        return range(2, 7)

    return (int(joiner_choice),)


def _joiner_label(joiner_choice):
    if joiner_choice == "all":
        return "All options (2–6 rallies)"

    return f"{joiner_choice} rallies"


def _calculator_embed(
    interaction,
    calculation,
    display_mode,
    basis_label,
    joiner_choice,
):
    lead = calculation["lead"]

    embed = discord.Embed(
        title="🐻 Kingshot Bear Troop Calculator",
        description=(
            f"Results for {interaction.user.mention}\n"
            f"Calculation basis: **{basis_label}**\n"
            f"Rallies to join: **{_joiner_label(joiner_choice)}**\n"
            "Ratio order: **Infantry / Cavalry / Archers**"
        ),
        color=discord.Color.orange(),
    )

    lead_lines = []

    if display_mode in ("ratios", "both"):
        lead_lines.append(
            f"Ratio: **{_ratio_text(lead['ratio'])}**"
        )

    if display_mode in ("troops", "both"):
        lead_lines.extend(
            [
                f"Infantry: **{lead['infantry']:,}**",
                f"Cavalry: **{lead['cavalry']:,}**",
                f"Archers: **{lead['archers']:,}**",
            ]
        )

    lead_lines.append(
        f"Total: **{lead['total']:,}**"
    )

    embed.add_field(
        name="Lead march",
        value="\n".join(lead_lines),
        inline=False,
    )

    for option in calculation["options"]:
        value_lines = []

        if display_mode in ("ratios", "both"):
            value_lines.append(
                f"Approx. ratio: "
                f"**{_ratio_text(option['ratio'])}**"
            )

        if display_mode in ("troops", "both"):
            value_lines.append(
                "**Troops per march:**"
            )
            value_lines.append(
                _per_march_text(option)
            )

        value_lines.append(
            f"Deployable: **{option['total_used']:,} / "
            f"{option['total_capacity']:,}** troops"
        )

        if not option["minimum_met"]:
            troop_names = ", ".join(
                troop_type.title()
                for troop_type in option["missing_minimums"]
            )

            value_lines.append(
                f"⚠️ Cannot maintain the 1% minimum for: "
                f"**{troop_names}**"
            )

        if not option["full"]:
            value_lines.append(
                f"⚠️ Short **{option['shortage']:,}** troops"
            )
        else:
            value_lines.append(
                "✅ All joiner marches can be filled"
            )

        embed.add_field(
            name=f"{option['joiner_count']} joiners",
            value="\n".join(value_lines),
            inline=False,
        )

    embed.set_footer(
        text=(
            "Joiners use one identical formation per march, "
            "with at least 1% of each troop type, then prioritize "
            "Archers → Cavalry → Infantry."
        )
    )

    return embed


def _normal_calculator_fields():
    return (
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
            parser=troop_count_value(
                "March Capacity",
                minimum=3,
            ),
        ),
        TextField(
            name="lead_ratio",
            label="Lead Ratio — Infantry/Cavalry/Archers",
            placeholder="Example: 1/9/90",
            required=True,
            parser=troop_ratio_value,
        ),
    )


def _troop_limit_capacity_fields():
    return (
        TextField(
            name="march_capacity",
            label="March Capacity",
            placeholder="Example: 134,710",
            required=True,
            parser=troop_count_value(
                "March Capacity",
                minimum=3,
            ),
        ),
        TextField(
            name="troop_limit",
            label="Troop Limit",
            placeholder="Example: 100,000",
            required=True,
            parser=troop_count_value(
                "Troop Limit",
                minimum=3,
            ),
        ),
    )


def _troop_limit_troop_fields():
    return (
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
            name="lead_ratio",
            label="Lead Ratio — Infantry/Cavalry/Archers",
            placeholder="Example: 1/9/90",
            required=True,
            parser=troop_ratio_value,
        ),
    )


class CalculatorSetupView(discord.ui.View):
    def __init__(self, owner_id, open_form):
        super().__init__(timeout=180)

        self.owner_id = owner_id
        self.open_form = open_form

        self.calculation_basis = "limit"
        self.display_mode = "troops"
        self.joiner_choice = "all"

        self.basis_select = discord.ui.Select(
            placeholder="Choose calculation method",
            min_values=1,
            max_values=1,
            row=0,
            options=[
                discord.SelectOption(
                    label="Use Troop Limit",
                    value="limit",
                    description="Use an event-specific troop limit",
                    default=True,
                ),
                discord.SelectOption(
                    label="Use March Capacity",
                    value="march",
                    description="Use your normal march capacity",
                ),
            ],
        )

        self.display_select = discord.ui.Select(
            placeholder="Choose results to show",
            min_values=1,
            max_values=1,
            row=1,
            options=[
                discord.SelectOption(
                    label="Show me troop counts",
                    value="troops",
                    default=True,
                ),
                discord.SelectOption(
                    label="Show me ratios",
                    value="ratios",
                ),
                discord.SelectOption(
                    label="Show me both",
                    value="both",
                ),
            ],
        )

        self.joiner_select = discord.ui.Select(
            placeholder="How many rallies do you want to join?",
            min_values=1,
            max_values=1,
            row=2,
            options=[
                discord.SelectOption(
                    label="Show all rally options",
                    value="all",
                    description="Compare joining 2–6 rallies",
                    default=True,
                ),
                discord.SelectOption(
                    label="Join 2 rallies",
                    value="2",
                ),
                discord.SelectOption(
                    label="Join 3 rallies",
                    value="3",
                ),
                discord.SelectOption(
                    label="Join 4 rallies",
                    value="4",
                ),
                discord.SelectOption(
                    label="Join 5 rallies",
                    value="5",
                ),
                discord.SelectOption(
                    label="Join 6 rallies",
                    value="6",
                ),
            ],
        )

        self.continue_button = discord.ui.Button(
            label="Continue",
            style=discord.ButtonStyle.primary,
            emoji="🐻",
            row=3,
        )

        self.basis_select.callback = self._basis_changed
        self.display_select.callback = self._display_changed
        self.joiner_select.callback = self._joiner_changed
        self.continue_button.callback = self._continue

        self.add_item(self.basis_select)
        self.add_item(self.display_select)
        self.add_item(self.joiner_select)
        self.add_item(self.continue_button)

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Please run `/bear calculator` to open your own calculator.",
                ephemeral=True,
            )
            return False

        return True

    async def _basis_changed(
        self,
        interaction: discord.Interaction,
    ):
        self.calculation_basis = self.basis_select.values[0]
        await interaction.response.defer()

    async def _display_changed(
        self,
        interaction: discord.Interaction,
    ):
        self.display_mode = self.display_select.values[0]
        await interaction.response.defer()

    async def _joiner_changed(
        self,
        interaction: discord.Interaction,
    ):
        self.joiner_choice = self.joiner_select.values[0]
        await interaction.response.defer()

    async def _continue(
        self,
        interaction: discord.Interaction,
    ):
        await self.open_form(
            interaction,
            self.calculation_basis,
            self.display_mode,
            self.joiner_choice,
        )


class TroopLimitContinueView(discord.ui.View):
    def __init__(
        self,
        owner_id,
        march_capacity,
        troop_limit,
        display_mode,
        joiner_choice,
        open_troop_form,
    ):
        super().__init__(timeout=180)

        self.owner_id = owner_id
        self.march_capacity = march_capacity
        self.troop_limit = troop_limit
        self.display_mode = display_mode
        self.joiner_choice = joiner_choice
        self.open_troop_form = open_troop_form

        button = discord.ui.Button(
            label="Continue",
            style=discord.ButtonStyle.primary,
            emoji="🐻",
        )

        button.callback = self._continue
        self.add_item(button)

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Please run `/bear calculator` to open your own calculator.",
                ephemeral=True,
            )
            return False

        return True

    async def _continue(
        self,
        interaction: discord.Interaction,
    ):
        await self.open_troop_form(
            interaction,
            self.march_capacity,
            self.troop_limit,
            self.display_mode,
            self.joiner_choice,
        )


def register_calculator_command(group, log_event):

    async def open_normal_form(
        interaction,
        display_mode,
        joiner_choice,
    ):
        async def submit_calculator(
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
                joiner_counts=_joiner_counts(joiner_choice),
            )

            await interaction.response.send_message(
                embed=_calculator_embed(
                    interaction,
                    calculation,
                    display_mode,
                    "March Capacity",
                    joiner_choice,
                )
            )

        await interaction.response.send_modal(
            CommandFormModal(
                title="Bear troop calculator",
                submit_handler=submit_calculator,
                fields=_normal_calculator_fields(),
            )
        )

    async def open_troop_limit_troop_form(
        interaction,
        march_capacity,
        troop_limit,
        display_mode,
        joiner_choice,
    ):
        async def submit_calculator(
            interaction,
            infantry,
            cavalry,
            archers,
            lead_ratio,
        ):
            calculation = calculate_bear_deployment(
                infantry,
                cavalry,
                archers,
                march_capacity,
                lead_ratio,
                joiner_capacity=troop_limit,
                joiner_counts=_joiner_counts(joiner_choice),
            )

            await interaction.response.send_message(
                embed=_calculator_embed(
                    interaction,
                    calculation,
                    display_mode,
                    "Troop Limit",
                    joiner_choice,
                )
            )

        await interaction.response.send_modal(
            CommandFormModal(
                title="Enter troops and lead ratio",
                submit_handler=submit_calculator,
                fields=_troop_limit_troop_fields(),
            )
        )

    async def open_troop_limit_form(
        interaction,
        display_mode,
        joiner_choice,
    ):
        async def submit_capacities(
            interaction,
            march_capacity,
            troop_limit,
        ):
            view = TroopLimitContinueView(
                interaction.user.id,
                march_capacity,
                troop_limit,
                display_mode,
                joiner_choice,
                open_troop_limit_troop_form,
            )

            await interaction.response.send_message(
                (
                    "March information saved.\n\n"
                    f"**March Capacity:** {march_capacity:,}\n"
                    f"**Troop Limit:** {troop_limit:,}\n"
                    f"**Rallies to join:** {_joiner_label(joiner_choice)}\n\n"
                    "Click **Continue** to enter troop totals "
                    "and your lead ratio."
                ),
                view=view,
                ephemeral=True,
            )

        await interaction.response.send_modal(
            CommandFormModal(
                title="Enter march limits",
                submit_handler=submit_capacities,
                fields=_troop_limit_capacity_fields(),
            )
        )

    async def open_selected_form(
        interaction,
        calculation_basis,
        display_mode,
        joiner_choice,
    ):
        if calculation_basis == "march":
            await open_normal_form(
                interaction,
                display_mode,
                joiner_choice,
            )
        else:
            await open_troop_limit_form(
                interaction,
                display_mode,
                joiner_choice,
            )

    @group.command(
        name="calculator",
        description="Calculate lead and joiner troop deployments",
    )
    @log_discord_request(
        log_event,
        "/bear calculator",
    )
    async def calculator(interaction):
        view = CalculatorSetupView(
            interaction.user.id,
            open_selected_form,
        )

        await interaction.response.send_message(
            (
                "🐻 **Bear Calculator Setup**\n\n"
                "Choose how the calculator should work, "
                "then click **Continue**."
            ),
            view=view,
            ephemeral=True,
        )