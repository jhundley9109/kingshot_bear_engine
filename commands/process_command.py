import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands

from services.extraction_review_service import (
    build_extraction_preview,
    extract_bear_data,
    find_image_attachments,
    merge_players,
)
from views.review_views import BearTrapReviewView


def register_process_command(
    command_tree,
    configured_guilds,
    repository,
    openai_client,
    log_event,
):
    @app_commands.context_menu(name="Process Bear Trap")
    async def process_bear_trap(
        interaction: discord.Interaction,
        message: discord.Message,
    ):
        report_submitted_at = datetime.now(timezone.utc)
        log_event("Received Bear Trap processing request.")
        await interaction.response.defer(ephemeral=True, thinking=True)

        images = find_image_attachments(message.attachments)
        if not images:
            await interaction.followup.send(
                "❌ I couldn't find any images attached to that message.",
                ephemeral=True,
            )
            return

        try:
            data = await asyncio.to_thread(
                extract_bear_data,
                openai_client,
                [image.url for image in images],
            )
            log_event("Received OpenAI Bear Trap extraction response.")
            merged_players, conflicts = merge_players(data.get("players", []))
            existing_event_id = await asyncio.to_thread(
                repository.find_existing_report, data, message
            )
            result = build_extraction_preview(
                data,
                merged_players,
                conflicts,
                len(images),
                existing_event_id,
            )

            review_view = None
            if not conflicts:
                review_view = BearTrapReviewView(
                    repository,
                    data,
                    merged_players,
                    message,
                    interaction.user.id,
                    report_submitted_at,
                    existing_event_id,
                )

            send_options = {"ephemeral": True}
            if review_view is not None:
                send_options["view"] = review_view
            await interaction.followup.send(result, **send_options)
        except Exception as error:
            log_event(f"Error processing Bear Trap: {error}")
            await interaction.followup.send(
                "❌ I ran into an error while processing those screenshots. "
                "Check the bot's terminal for the error.",
                ephemeral=True,
            )

    command_tree.add_command(process_bear_trap, guilds=configured_guilds)
