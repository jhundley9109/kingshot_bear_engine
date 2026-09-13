import unicodedata


DISCORD_MESSAGE_LIMIT = 1900
DISCORD_TEXT_CHUNK_LIMIT = 1750


def table_text(value, width):
    value = str(value).replace("`", "'")
    if len(value) <= width:
        return value
    return value[: width - 3] + "..."


def damage_text(value):
    return f"{int(value or 0):,}"


def code_table_chunks(
    header,
    separator,
    rows,
    title=None,
    continued_title=None,
    max_length=DISCORD_MESSAGE_LIMIT,
):
    def start_chunk(chunk_title):
        prefix = [chunk_title] if chunk_title else []
        return prefix + ["```text", header, separator]

    chunks = []
    current = start_chunk(title)
    for row in rows:
        if len("\n".join(current + [row, "```"])) > max_length:
            current.append("```")
            chunks.append("\n".join(current))
            next_title = continued_title
            if next_title is None and title:
                next_title = f"{title} **(continued)**"
            current = start_chunk(next_title)
        current.append(row)
    current.append("```")
    chunks.append("\n".join(current))
    return chunks


def discord_text_chunks(text, max_length=DISCORD_TEXT_CHUNK_LIMIT):
    chunks = []
    remaining = text.strip()
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def paged_text_messages(
    heading,
    text,
    context_line=None,
    page_body_limit=1200,
    max_length=DISCORD_MESSAGE_LIMIT,
):
    """Build labeled message pages while accounting for heading length."""
    page_label_reserve = "*Page 9999 of 9999*"
    first_header_parts = [heading, page_label_reserve]
    if context_line:
        first_header_parts.append(context_line)
    first_header_reserve = "\n".join(first_header_parts)
    continued_header_reserve = f"{heading}\n{page_label_reserve}"
    body_limit = min(
        page_body_limit,
        max_length - max(
            len(first_header_reserve),
            len(continued_header_reserve),
        ) - 2,
    )
    if body_limit <= 0:
        raise ValueError("The page heading is too long for a Discord message.")

    body_chunks = discord_text_chunks(text, max_length=body_limit)
    if not body_chunks:
        return [heading if not context_line else f"{heading}\n{context_line}"]
    if len(body_chunks) == 1:
        header = heading if not context_line else f"{heading}\n{context_line}"
        return [f"{header}\n\n{body_chunks[0]}"]

    messages = []
    page_count = len(body_chunks)
    for index, body in enumerate(body_chunks, start=1):
        header_parts = [heading, f"*Page {index} of {page_count}*"]
        if index == 1 and context_line:
            header_parts.append(context_line)
        header = "\n".join(header_parts)
        messages.append(f"{header}\n\n{body}")
    return messages


def line_chunks(
    initial_lines,
    rows,
    continued_lines=None,
    max_length=DISCORD_MESSAGE_LIMIT,
):
    chunks = []
    current = list(initial_lines)
    for row in rows:
        if len("\n".join(current + [row])) > max_length:
            chunks.append("\n".join(current))
            current = list(continued_lines or [])
        current.append(row)
    chunks.append("\n".join(current))
    return chunks


def has_rtl_text(value):
    return any(
        unicodedata.bidirectional(character) in {"R", "AL", "AN"}
        for character in value
    )


def table_name_cell(value, width):
    value = table_text(value, width)
    padding = " " * max(0, width - len(value))
    if has_rtl_text(value):
        return f"{padding}\u2067{value}\u2069"
    return f"{padding}{value}"


def channel_label(value):
    return value or "unknown-channel"


def guild_label(name, guild_id):
    return f"{name or 'unknown-server'} ({guild_id or 'unknown-guild-id'})"


def guild_scope_line(rows):
    guilds = sorted({
        guild_label(row["discord_guild_name"], row["discord_guild_id"])
        for row in rows
        if row["discord_guild_id"] is not None
    })
    if not guilds:
        return None
    return "Guilds: **" + "**, **".join(guilds) + "**"


def player_result_context(result, all_channels=False, all_servers=False):
    date_label = result["event_date"] or "Unknown date"
    if result["event_time"]:
        date_label += f" {result['event_time']}"

    channel_prefix = ""
    if all_channels or all_servers:
        server_prefix = ""
        if all_servers:
            server_prefix = guild_label(
                result["discord_guild_name"], result["discord_guild_id"]
            ) + " / "
        channel_prefix = (
            f"{server_prefix}#{channel_label(result['discord_channel_name'])} — "
        )

    uncertain = " ⚠️" if result["uncertain"] else ""
    return f"{channel_prefix}{date_label}", uncertain
