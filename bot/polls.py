"""Native Discord polls: general builder, raid availability preset, schedules.

Registered from bot/commands.py after ``client`` exists, the way questboard is.
The raid preset mirrors the two polls the FC posts by hand each week: a
multi-select day poll labelled with the week's dates, then a single-select
time-of-day poll.

Schedules are stored in core.pollstore with a local weekday/time and an IANA
zone, so a Friday 18:00 schedule stays at 18:00 through DST changes. The loop
scans every POLL_LOOP_INTERVAL seconds and posts at most once per local day.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import discord
from discord import app_commands

from core import pollstore

POLL_LOOP_INTERVAL = 30  # seconds between due-schedule scans
RAID_DEFAULT_START_HOUR = 16  # 4 pm, matching the hand-posted polls
RAID_DEFAULT_SLOTS = 4

WEEKDAY_CHOICES = [
    app_commands.Choice(name=day, value=index)
    for index, day in enumerate(pollstore.WEEKDAYS)
]


class PollClient(Protocol):
    """The slice of the bot client the poll commands and loop actually use.

    discord.py's Client does not declare ``tree`` (only the bot subclass has
    it), so depending on the whole Client type would either be a lie or force
    an Any. This states the real contract instead.
    """

    tree: app_commands.CommandTree[Any]  # the client type parameter is unused

    def get_channel(
        self, id: int, /
    ) -> discord.abc.GuildChannel | discord.Thread | discord.abc.PrivateChannel | None: ...

    def is_closed(self) -> bool: ...


# --- poll construction -----------------------------------------------------


def build_poll(
    question: str, options: list[str], *, multiple: bool, duration_hours: int
) -> discord.Poll:
    """Build a native Discord poll with *options* as its answers."""
    poll = discord.Poll(
        question,
        duration=timedelta(hours=duration_hours),
        multiple=multiple,
    )
    for text in options:
        poll.add_answer(text=text)
    return poll


async def post_raid_pair(
    channel: discord.TextChannel,
    *,
    week_start: date,
    timezone: str,
    start_hour: int = RAID_DEFAULT_START_HOUR,
    slots: int = RAID_DEFAULT_SLOTS,
    duration_hours: int = 24,
    multi_days: bool = True,
) -> list[discord.Message]:
    """Post the day poll and the time poll for one raid week."""
    week_end = week_start + timedelta(days=6)
    day_poll = build_poll(
        pollstore.raid_question(week_start, week_end),
        list(pollstore.WEEKDAYS),
        multiple=multi_days,
        duration_hours=duration_hours,
    )
    time_poll = build_poll(
        "What time would work best for you?",
        pollstore.slot_labels(start_hour, slots, timezone, week_start),
        multiple=False,
        duration_hours=duration_hours,
    )
    return [await channel.send(poll=day_poll), await channel.send(poll=time_poll)]


# --- command registration --------------------------------------------------


def register_poll_commands(client: PollClient) -> None:
    tree = client.tree
    group = app_commands.Group(name="poll", description="Post and schedule Discord polls")

    async def _guild_id(interaction: discord.Interaction) -> str | None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Polls can only be scheduled inside a server.", ephemeral=True
            )
            return None
        return str(interaction.guild_id)

    @group.command(name="create", description="Post a native Discord poll")
    @app_commands.describe(
        question="Poll question",
        options="Answers separated by | or new lines (2 to 10)",
        channel="Channel to post in",
        duration_hours="How long the poll stays open (1 to 768 hours)",
        multi="Allow more than one answer",
    )
    async def poll_create(
        interaction: discord.Interaction,
        question: str,
        options: str,
        channel: discord.TextChannel,
        duration_hours: int = 24,
        multi: bool = False,
    ) -> None:
        try:
            answers = pollstore.parse_options(options)
            pollstore.validate_duration(duration_hours)
            question = pollstore.validate_question(question)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            message = await channel.send(
                poll=build_poll(
                    question, answers, multiple=multi, duration_hours=duration_hours
                )
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not post the poll: {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            f"Poll posted in {channel.mention}: {message.jump_url}", ephemeral=True
        )

    @group.command(
        name="raid", description="Post the weekly day and time availability polls"
    )
    @app_commands.describe(
        channel="Channel to post in",
        timezone="IANA zone for the time labels, default is the bot's local zone",
        week_offset="0 asks about the upcoming Mon-Sun week, 1 the week after",
        start_hour="First time slot, local hour (default 16 = 4 pm)",
        slots="How many hourly time slots to offer",
        duration_hours="How long each poll stays open",
        multi_days="Allow more than one day to be picked",
    )
    async def poll_raid(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        timezone: str | None = None,
        week_offset: int = 0,
        start_hour: int = RAID_DEFAULT_START_HOUR,
        slots: int = RAID_DEFAULT_SLOTS,
        duration_hours: int = 24,
        multi_days: bool = True,
    ) -> None:
        try:
            pollstore.validate_raid_options(start_hour, slots, week_offset)
            pollstore.validate_duration(duration_hours)
            zone = pollstore.resolve_timezone(timezone)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        week_start = pollstore.week_start_for(datetime.now(zone).date(), week_offset)
        await interaction.response.defer(ephemeral=True)
        try:
            messages = await post_raid_pair(
                channel,
                week_start=week_start,
                timezone=timezone or pollstore.local_timezone_name(),
                start_hour=start_hour,
                slots=slots,
                duration_hours=duration_hours,
                multi_days=multi_days,
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"Could not post the polls: {exc}", ephemeral=True
            )
            return
        links = ", ".join(message.jump_url for message in messages)
        await interaction.followup.send(
            f"Week of {week_start.strftime('%d.%m.%Y')} posted in {channel.mention}: {links}",
            ephemeral=True,
        )

    @group.command(
        name="schedule-add", description="Repeat a custom poll weekly (administrator)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(weekday=WEEKDAY_CHOICES)
    @app_commands.describe(
        name="Label shown in the schedule list",
        channel="Channel to post in",
        weekday="Day of the week",
        time_of_day="Post time as HH:MM in the schedule's timezone",
        question="Poll question",
        options="Answers separated by | or new lines (2 to 10)",
        timezone="IANA zone, default is the bot's local zone",
        duration_hours="How long the poll stays open",
        multi="Allow more than one answer",
    )
    async def schedule_add(
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        weekday: app_commands.Choice[int],
        time_of_day: str,
        question: str,
        options: str,
        timezone: str | None = None,
        duration_hours: int = 24,
        multi: bool = False,
    ) -> None:
        guild_id = await _guild_id(interaction)
        if guild_id is None:
            return
        zone_name = timezone or pollstore.local_timezone_name()
        try:
            answers = pollstore.parse_options(options)
            hour, minute = pollstore.parse_time_of_day(time_of_day)
            schedule_id = pollstore.create_schedule(
                guild_id=guild_id,
                channel_id=str(channel.id),
                name=name,
                preset=pollstore.PRESET_CUSTOM,
                weekday_local=weekday.value,
                hour_local=hour,
                minute_local=minute,
                timezone=zone_name,
                created_by=str(interaction.user.id),
                question=question,
                options=answers,
                multi=multi,
                duration_hours=duration_hours,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Schedule #{schedule_id} saved: {name}, every "
            f"{pollstore.WEEKDAYS[weekday.value]} at {time_of_day} {zone_name} in "
            f"{channel.mention}.",
            ephemeral=True,
        )

    @group.command(
        name="schedule-raid",
        description="Repeat the weekly day and time polls on a schedule (administrator)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(weekday=WEEKDAY_CHOICES)
    @app_commands.describe(
        name="Label shown in the schedule list",
        channel="Channel to post in",
        weekday="Day of the week the polls are posted",
        time_of_day="Post time as HH:MM in the schedule's timezone",
        timezone="IANA zone, default is the bot's local zone",
        start_hour="First time slot, local hour (default 16 = 4 pm)",
        slots="How many hourly time slots to offer",
        week_offset="0 asks about the upcoming Mon-Sun week, 1 the week after",
        duration_hours="How long each poll stays open",
        multi_days="Allow more than one day to be picked",
    )
    async def schedule_raid(
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        weekday: app_commands.Choice[int],
        time_of_day: str,
        timezone: str | None = None,
        start_hour: int = RAID_DEFAULT_START_HOUR,
        slots: int = RAID_DEFAULT_SLOTS,
        week_offset: int = 0,
        duration_hours: int = 24,
        multi_days: bool = True,
    ) -> None:
        guild_id = await _guild_id(interaction)
        if guild_id is None:
            return
        zone_name = timezone or pollstore.local_timezone_name()
        try:
            hour, minute = pollstore.parse_time_of_day(time_of_day)
            schedule_id = pollstore.create_schedule(
                guild_id=guild_id,
                channel_id=str(channel.id),
                name=name,
                preset=pollstore.PRESET_RAID,
                weekday_local=weekday.value,
                hour_local=hour,
                minute_local=minute,
                timezone=zone_name,
                created_by=str(interaction.user.id),
                duration_hours=duration_hours,
                time_start_hour=start_hour,
                time_slots=slots,
                week_offset=week_offset,
                multi=multi_days,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Schedule #{schedule_id} saved: raid polls every "
            f"{pollstore.WEEKDAYS[weekday.value]} at {time_of_day} {zone_name} in "
            f"{channel.mention}.",
            ephemeral=True,
        )

    @group.command(name="schedule-list", description="List weekly poll schedules")
    async def schedule_list(interaction: discord.Interaction) -> None:
        guild_id = await _guild_id(interaction)
        if guild_id is None:
            return
        entries = pollstore.list_schedules(guild_id)
        if not entries:
            await interaction.response.send_message(
                "No poll schedules yet. Add one with /poll schedule-raid.",
                ephemeral=True,
            )
            return
        lines = []
        for entry in entries:
            day = pollstore.WEEKDAYS[int(entry["weekday_local"])]
            clock = f"{int(entry['hour_local']):02d}:{int(entry['minute_local']):02d}"
            lines.append(
                f"#{entry['id']} **{entry['name']}** - {entry['preset']}, "
                f"{day} {clock} {entry['timezone']} in <#{entry['channel_id']}>"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @group.command(
        name="schedule-remove", description="Delete a weekly poll schedule (administrator)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(schedule_id="Schedule number from /poll schedule-list")
    async def schedule_remove(
        interaction: discord.Interaction, schedule_id: int
    ) -> None:
        guild_id = await _guild_id(interaction)
        if guild_id is None:
            return
        if pollstore.delete_schedule(schedule_id, guild_id):
            await interaction.response.send_message(
                f"Schedule #{schedule_id} removed.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"No schedule #{schedule_id} in this server.", ephemeral=True
            )

    tree.add_command(group)


# --- schedule loop ---------------------------------------------------------


async def _post_scheduled(channel: discord.TextChannel, entry: dict[str, Any]) -> None:
    try:
        if entry["preset"] == pollstore.PRESET_RAID:
            local_date = date.fromisoformat(str(entry["local_date"]))
            await post_raid_pair(
                channel,
                week_start=pollstore.week_start_for(
                    local_date, int(entry["week_offset"])
                ),
                timezone=str(entry["timezone"]),
                start_hour=int(entry["time_start_hour"]),
                slots=int(entry["time_slots"]),
                duration_hours=int(entry["duration_hours"]),
                multi_days=bool(entry["multi"]),
            )
        else:
            await channel.send(
                poll=build_poll(
                    str(entry["question"]),
                    list(entry["options"]),
                    multiple=bool(entry["multi"]),
                    duration_hours=int(entry["duration_hours"]),
                )
            )
    except discord.HTTPException:
        logging.exception("poll schedule %s failed to post", entry["id"])
        return

    pollstore.mark_posted(int(entry["id"]), str(entry["local_date"]))
    logging.info("poll schedule %s posted in channel %s", entry["id"], entry["channel_id"])


async def poll_loop(client: PollClient) -> None:
    """Scan weekly poll schedules and post the ones that are due."""
    await asyncio.sleep(20)
    logging.info("Poll schedule loop started.")
    while not client.is_closed():
        try:
            for entry in pollstore.due_schedules():
                channel = client.get_channel(int(entry["channel_id"]))
                if not isinstance(channel, discord.TextChannel):
                    logging.warning(
                        "poll schedule %s: channel %s is not a reachable text channel",
                        entry["id"],
                        entry["channel_id"],
                    )
                    continue
                await _post_scheduled(channel, entry)
        except Exception:  # noqa: BLE001 - the loop must survive anything
            logging.exception("poll schedule loop iteration failed")
        await asyncio.sleep(POLL_LOOP_INTERVAL)
