from dataclasses import dataclass

import discord


def integer_value(label, default=None, minimum=None, maximum=None):
    def parse(value):
        if not value:
            return default
        try:
            result = int(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a whole number.") from error
        if minimum is not None and result < minimum:
            raise ValueError(f"{label} must be at least {minimum}.")
        if maximum is not None and result > maximum:
            raise ValueError(f"{label} must be at most {maximum}.")
        return result

    return parse


def text_value(value):
    return value.strip()


@dataclass(frozen=True)
class TextField:
    name: str
    label: str
    placeholder: str = None
    required: bool = False
    default: str = None
    max_length: int = 100
    parser: object = text_value


@dataclass(frozen=True)
class SelectField:
    name: str
    label: str
    options: tuple
    description: str = None
    parser: object = text_value


class CommandFormModal(discord.ui.Modal):
    def __init__(self, title, submit_handler, fields=(), include_scope=False):
        super().__init__(title=title, timeout=900)
        self.submit_handler = submit_handler
        self.form_fields = []

        for field in fields:
            if isinstance(field, TextField):
                component = discord.ui.TextInput(
                    placeholder=field.placeholder,
                    default=field.default,
                    required=field.required,
                    max_length=field.max_length,
                )
                label = discord.ui.Label(text=field.label, component=component)
            else:
                component = discord.ui.Select(
                    options=[
                        discord.SelectOption(
                            label=option[0],
                            value=option[1],
                            default=len(option) > 2 and option[2],
                        )
                        for option in field.options
                    ],
                    required=True,
                    min_values=1,
                    max_values=1,
                )
                label = discord.ui.Label(
                    text=field.label,
                    description=field.description,
                    component=component,
                )
            self.form_fields.append((field, component))
            self.add_item(label)

        self.scope_select = None
        self.channel_select = None
        if include_scope:
            self.scope_select = discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label="Current or selected channel",
                        value="channel",
                        default=True,
                    ),
                    discord.SelectOption(
                        label="All channels in this server",
                        value="all_channels",
                    ),
                    discord.SelectOption(
                        label="All configured servers (owner only)",
                        value="all_servers",
                    ),
                ],
                required=True,
                min_values=1,
                max_values=1,
            )
            self.add_item(
                discord.ui.Label(
                    text="Report scope",
                    description="Defaults to the channel where you ran the command.",
                    component=self.scope_select,
                )
            )

            self.channel_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text],
                required=False,
                min_values=0,
                max_values=1,
            )
            self.add_item(
                discord.ui.Label(
                    text="Channel override (optional)",
                    description="Used only with the current/selected channel scope.",
                    component=self.channel_select,
                )
            )

    async def on_submit(self, interaction):
        try:
            values = {}
            for field, component in self.form_fields:
                raw_value = (
                    component.value
                    if isinstance(field, TextField)
                    else component.values[0]
                )
                values[field.name] = field.parser(raw_value)

            if self.scope_select is not None:
                selected_scope = self.scope_select.values[0]
                selected_channels = self.channel_select.values
                values.update(
                    channel=(
                        selected_channels[0]
                        if selected_scope == "channel" and selected_channels
                        else None
                    ),
                    all_channels=selected_scope == "all_channels",
                    all_servers=selected_scope == "all_servers",
                )
            await self.submit_handler(interaction, **values)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)


def command_form(title, fields=(), include_scope=False):
    def decorator(submit_handler):
        async def open_form(interaction: discord.Interaction):
            await interaction.response.send_modal(
                CommandFormModal(
                    title=title,
                    submit_handler=submit_handler,
                    fields=fields,
                    include_scope=include_scope,
                )
            )

        open_form.__name__ = submit_handler.__name__
        open_form.__qualname__ = submit_handler.__qualname__
        open_form.__doc__ = submit_handler.__doc__
        return open_form

    return decorator
