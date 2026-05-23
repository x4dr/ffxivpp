"""FF14 Party Planner — Discord bot commands."""

# mypy: ignore-errors
# discord.py UI component stubs are incomplete (parent property, generics)

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import asyncio
import os
import random
import re
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from discord.ui import Button, Select, View

from app.compute import JOBS, JOBS_BY_ID, get_priority, parse_job_id
from app.db import (
    Session,
    add_role_id,
    remove_role_id,
    get_lodestone_link,
)
from app.models import AppState, LodestoneLink, PartyPerson, Person, Party

VALID_JOBS = {j.id for j in JOBS}
JOB_NAMES = {j.id: j.name for j in JOBS}
ROLES = [
    ("tank", "Tank", "🛡️"),
    ("healer", "Healer", "💚"),
    ("melee", "Melee", "⚔️"),
    ("pranged", "Phys Ranged", "🏹"),
    ("caster", "Caster", "🔮"),
]
ROLE_JOBS: dict[str, list[str]] = {
    "tank": [j.id for j in JOBS if j.sub == "tank"],
    "healer": [j.id for j in JOBS if j.role == "healer"],
    "melee": [j.id for j in JOBS if j.sub == "melee"],
    "pranged": [j.id for j in JOBS if j.sub == "pranged"],
    "caster": [j.id for j in JOBS if j.sub == "caster"],
}


def parse_jobs(s: str) -> list[str]:
    raw = [j.strip().lower() for j in re.split(r"[^a-z0-9:]+", s) if j.strip()]
    out: list[str] = []
    for entry in raw:
        parts = entry.split(":")
        jid = parts[0]
        if jid in VALID_JOBS:
            if len(parts) > 1 and parts[1].isdigit():
                out.append(f"{jid}:{parts[1]}")
            else:
                out.append(jid)
    return out


# ── Bot client ──────────────────────────────────────────────────────────


class PartyBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        if not os.environ.get("BASE_URL"):
            raise RuntimeError("BASE_URL environment variable must be set before starting the bot.")
        self.add_view(PersistentPartyView())

        # Sync all commands globally
        await self.tree.sync()

        self.loop.create_task(self.scraper_loop())

    async def scraper_loop(self) -> None:
        """Background loop to refresh character data with optimized DB locking."""
        from app.db import (
            cache_character,
            Session,
            delete_scraper_task,
            get_next_scraper_task,
            get_parties_for_lodestone_id,
            set_lodestone_link,
            update_lodestone_fetched_at,
        )
        from app.lodestone import fetch_character
        from app.models import LodestoneLink

        loop = asyncio.get_event_loop()
        await asyncio.sleep(10)
        logging.info("Scraper loop started.")

        while not self.is_closed():
            try:
                task = get_next_scraper_task()
                person_id = None

                if task:
                    lodestone_id = task['lodestone_id']
                    try:
                        link = Session.query(LodestoneLink).filter_by(lodestone_id=lodestone_id).first()
                        person_id = link.person_id if link else None
                    finally:
                        Session.remove()
                    logging.info(f"Scraping high-priority {lodestone_id}...")
                    sleep_time = 1
                    is_priority = True
                else:
                    # Fallback to regular task
                    try:
                        link = Session.query(LodestoneLink).order_by(LodestoneLink.fetched_at.asc()).first()
                        lodestone_id = link.lodestone_id if link else None
                        person_id = link.person_id if link else None
                    finally:
                        Session.remove()
                    sleep_time = 10
                    is_priority = False

                if lodestone_id:
                    # 2. NETWORK IO: Run without holding any DB lock
                    data = await loop.run_in_executor(None, fetch_character, lodestone_id)

                    # 3. WRITE: Open only when needed using context manager
                    if data and "name" in data:
                        cache_character(lodestone_id, data)
                        update_lodestone_fetched_at(lodestone_id)
                        if person_id:
                            set_lodestone_link(person_id, lodestone_id, data["name"])

                        # Find party/channel/message to update
                        parties_to_update = get_parties_for_lodestone_id(lodestone_id)
                        for party_info in parties_to_update:
                            channel = self.get_channel(int(party_info['channel_id']))
                            if channel and isinstance(channel, discord.TextChannel):
                                try:
                                    message = await channel.fetch_message(int(party_info['message_id']))
                                    view = PersistentPartyView()
                                    await view.update_embed(channel, message)
                                except Exception as e:
                                    logging.error(f"Failed to update embed for {party_info['name']}: {e}")

                        if is_priority:
                            delete_scraper_task(lodestone_id)

                    logging.info(f"Finished scraping {lodestone_id}.")
                else:
                    await asyncio.sleep(sleep_time) # Wait if no tasks at all
                    continue # Skip the trailing sleep if we just did a wait

            except Exception as e:
                logging.error(f"Scraper error: {e}")
            await asyncio.sleep(sleep_time)



    async def on_ready(self) -> None:
        print(f"Bot logged in as {self.user}")
        self.add_view(PersistentPartyView())
        if self.application and self.application.owner:
            owner_id = str(self.application.owner.id)

            try:
                state = Session.query(AppState).filter_by(key='bot_owner_id').first()
                if state:
                    state.value = owner_id
                else:
                    Session.add(AppState(key='bot_owner_id', value=owner_id))
                Session.commit()
            finally:
                Session.remove()
            print(f"Bot owner ID stored: {owner_id}")


client = PartyBot()


@client.tree.error
async def on_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need the **Administrator** permission to use this command.", ephemeral=True
        )
    else:
        await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)


# ── Helpers ─────────────────────────────────────────────────────────────


def _load_person(name: str, discord_id: str | None = None) -> list[dict[str, Any]]:
    from app.db import people_pool

    current = people_pool()
    if discord_id:
        return [p for p in current if p.get("discord_id") != discord_id]
    return [p for p in current if p["name"] != name]


def _save_person(name: str, jids: list[str], discord_id: str | None = None) -> None:
    from app.db import people_pool, pool_save

    current = people_pool()
    if discord_id:
        current = [p for p in current if p.get("discord_id") != discord_id]
    else:
        current = [p for p in current if p["name"] != name]
    entry: dict[str, Any] = {"name": name, "jobs": jids}
    if discord_id:
        entry["discord_id"] = discord_id
    current.append(entry)
    pool_save(current)
    if discord_id:
        try:
            if not Session.query(PartyPerson).filter_by(party_name='Default', person_name=name).first():
                Session.add(PartyPerson(party_name='Default', person_name=name))
                Session.commit()
        finally:
            Session.remove()


def _build_job_list(jobs: list[str]) -> str:
    parts: list[str] = []
    for entry in jobs:
        jid = parse_job_id(entry)
        name = JOB_NAMES.get(jid, jid.upper())
        parts.append(name)
    return "/".join(parts) if parts else "*none*"


# ── /setjobs (interactive UI) ──────────────────────────────────────────


@client.tree.command(name="setjobs", description="Set your available jobs")
async def setjobs(interaction: discord.Interaction) -> None:
    name = interaction.user.display_name
    current = _load_person(name)
    existing = current[0]["jobs"] if current else []
    view = MyJobsView(name, existing, interaction.user.id)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


class MyJobsView(View):
    def __init__(self, name: str, jobs: list[str], user_id: int) -> None:
        super().__init__(timeout=300)
        self.name = name
        self.jobs: list[tuple[str, int]] = [(parse_job_id(e), get_priority(e)) for e in jobs]
        self.user_id = user_id
        self._build()

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Your Jobs", color=discord.Color.blue())
        if self.jobs:
            lines: list[str] = []
            for jid, prio in self.jobs:
                j = JOBS_BY_ID.get(jid)
                lines.append(f"**{j.name if j else jid.upper()}** — priority {prio}")
            embed.description = "\n".join(lines)
        else:
            embed.description = "No jobs set yet. Pick a role below to add some."
        embed.set_footer(text="Changes are saved automatically.")
        return embed

    def _build(self) -> None:
        self.clear_items()
        self.add_item(RoleSelect(self))
        if self.jobs:
            self.add_item(JobAdjustSelect(self))

    def _save(self) -> None:
        job_strs = [f"{jid}:{prio}" for jid, prio in self.jobs]
        _save_person(self.name, job_strs, str(self.user_id))

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: Any) -> None:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)


class RoleSelect(Select):
    def __init__(self, parent: MyJobsView) -> None:
        opts: list[discord.SelectOption] = []
        for role, label, emoji in ROLES:
            opts.append(discord.SelectOption(label=label, emoji=emoji, value=role))
        opts.append(discord.SelectOption(label="──────────", value="---", disabled=True))
        for role, label, emoji in ROLES:
            opts.append(discord.SelectOption(label=f"All {label}s", emoji=emoji, value=f"all_{role}"))
        super().__init__(placeholder="Add a job…", options=opts)
        self._main_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val.startswith("all_"):
            role = val.removeprefix("all_")
            for jid in ROLE_JOBS[role]:
                if not any(j == jid for j, _ in self._main_view.jobs):
                    self._main_view.jobs.append((jid, 5))
            self._main_view._save()
            self._main_view._build()
            await interaction.response.edit_message(embed=self._main_view.build_embed(), view=self._main_view)
            return
        jobs_for_role = ROLE_JOBS[val]
        view = JobPicker(self._main_view, jobs_for_role)
        await interaction.response.send_message("Pick a job to add:", view=view, ephemeral=True)


class JobPicker(View):
    def __init__(self, parent: MyJobsView, job_ids: list[str]) -> None:
        super().__init__(timeout=120)
        self._main_view = parent
        for jid in job_ids:
            name = JOB_NAMES.get(jid, jid.upper())
            self.add_item(JobButton(parent, jid, name))

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: Any) -> None:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)


class JobButton(Button):
    def __init__(self, parent: MyJobsView, jid: str, label: str) -> None:
        style_map = {
            "tank": discord.ButtonStyle.primary,
            "healer": discord.ButtonStyle.success,
            "melee": discord.ButtonStyle.danger,
            "pranged": discord.ButtonStyle.secondary,
            "caster": discord.ButtonStyle.secondary,
        }
        j = JOBS_BY_ID.get(jid)
        style = style_map.get(j.sub if j else "", discord.ButtonStyle.secondary)
        super().__init__(label=label, style=style)
        self._main_view = parent
        self.jid = jid

    async def callback(self, interaction: discord.Interaction) -> None:
        if not any(j == self.jid for j, _ in self._main_view.jobs):
            self._main_view.jobs.append((self.jid, 5))
        self._main_view._save()
        self._main_view._build()
        await interaction.response.edit_message(embed=self._main_view.build_embed(), view=self._main_view)


class JobAdjustSelect(Select):
    def __init__(self, parent: MyJobsView) -> None:
        opts = [
            discord.SelectOption(label=f"{JOB_NAMES.get(jid, jid.upper())} [prio {prio}]", value=f"{jid}:{prio}")
            for jid, prio in parent.jobs
        ]
        super().__init__(placeholder="Adjust or remove a job…", options=opts, max_values=1)
        self._main_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        jid, prio_str = self.values[0].split(":")
        prio = int(prio_str)
        view = JobActions(self._main_view, jid, prio)
        await interaction.response.send_message(
            f"**{JOB_NAMES.get(jid, jid.upper())}** — what now?", view=view, ephemeral=True
        )


class JobActions(View):
    def __init__(self, parent: MyJobsView, jid: str, priority: int) -> None:
        super().__init__(timeout=120)
        self._main_view = parent
        self.jid = jid
        self.add_item(PrioritySelect(parent, jid, priority))


class PrioritySelect(Select):
    def __init__(self, parent: MyJobsView, jid: str, priority: int) -> None:
        opts = [
            discord.SelectOption(label=f"Priority {p}", value=f"{p}", default=p == priority)
            for p in range(1, 11)
        ]
        opts.append(discord.SelectOption(label="Remove job", value="remove"))
        super().__init__(placeholder=f"Priority {priority}", options=opts)
        self._main_view = parent
        self.jid = jid

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "remove":
            self._main_view.jobs = [(j, p) for j, p in self._main_view.jobs if j != self.jid]
        else:
            new_prio = int(val)
            self._main_view.jobs = [(j, new_prio if j == self.jid else p) for j, p in self._main_view.jobs]
        self._main_view._save()
        self._main_view._build()
        await interaction.response.edit_message(embed=self._main_view.build_embed(), view=self._main_view)


# ── /setlodestone ──────────────────────────────────────────────────────


@client.tree.command(name="setlodestone", description="Link your FF14 Lodestone character")
@app_commands.describe(url="Your Lodestone character URL, e.g. https://eu.finalfantasyxiv.com/lodestone/character/54185648/")
async def setlodestone(interaction: discord.Interaction, url: str) -> None:
    m = re.search(r"/lodestone/character/(\d+)", url)
    if not m:
        await interaction.response.send_message(
            "Invalid Lodestone URL. Use the full URL from your character page.", ephemeral=True
        )
        return
    lodestone_id = m.group(1)

    await interaction.response.defer(ephemeral=True)

    from app.db import set_lodestone_link
    from app.lodestone import fetch_character

    data = fetch_character(lodestone_id)
    if "error" in data:
        await interaction.followup.send(data["error"], ephemeral=True)
        return

    # Find the person_id by discord_id
    try:
        person = Session.query(Person).filter_by(discord_id=str(interaction.user.id)).first()
    finally:
        Session.remove()

    if not person:
        await interaction.followup.send("Could not find a linked person for your Discord account.", ephemeral=True)
        return

    person_id = person.id
    set_lodestone_link(person_id, lodestone_id, data["name"])

    job_lines = []
    for jid, info in sorted(data.get("jobs", {}).items(), key=lambda x: -x[1].get("level", 0)):
        lv = info.get("level", "?")
        il = info.get("ilvl")
        il_str = f" — ilvl {il}" if il else ""
        job_lines.append(f"{jid.upper()} lv.{lv}{il_str}")

    embed = discord.Embed(
        title=f"Lodestone Linked — {data['name']}",
        description=f"[View on Lodestone](https://eu.finalfantasyxiv.com/lodestone/character/{lodestone_id}/)",
        color=discord.Color.green(),
    )
    if data.get("avg_ilvl"):
        embed.add_field(name="Average Item Level", value=str(data["avg_ilvl"]), inline=False)
    if job_lines:
        embed.add_field(name=f"Jobs ({len(job_lines)})", value="\n".join(job_lines[:15]), inline=False)
    if data.get("server"):
        embed.set_footer(text=f"{data['server']}  •  {data.get('source', '')}")

    await interaction.followup.send(embed=embed, ephemeral=True)


# ── Admin role commands ─────────────────────────────────────────────────


@client.tree.command(name="admin-role-add", description="Whitelist a role for admin panel access")
@app_commands.describe(role="Role to whitelist for admin panel access")
@app_commands.checks.has_permissions(administrator=True)
async def admin_role_add(interaction: discord.Interaction, role: discord.Role) -> None:
    guild_id = str(interaction.guild_id)
    add_role_id(guild_id, str(role.id))
    await interaction.response.send_message(
        f"Added {role.mention} to the admin panel whitelist.", ephemeral=True
    )


@client.tree.command(name="admin-role-remove", description="Remove a role from admin panel whitelist")
@app_commands.describe(role="Role to remove from whitelist")
@app_commands.checks.has_permissions(administrator=True)
async def admin_role_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    guild_id = str(interaction.guild_id)
    remove_role_id(guild_id, str(role.id))
    await interaction.response.send_message(
        f"Removed {role.mention} from the admin panel whitelist.", ephemeral=True
    )


class RecheckButton(Button):
    def __init__(self) -> None:
        super().__init__(label="Recheck Lodestone", style=discord.ButtonStyle.secondary, custom_id="recheck_lodestone")

    async def callback(self, interaction: discord.Interaction) -> None:
        from app.db import add_scraper_task, get_lodestone_link, people_pool

        user_id = str(interaction.user.id)
        person = next((p for p in people_pool() if p.get("discord_id") == user_id), None)

        if not person:
            await interaction.response.send_message("You are not registered in the bot.", ephemeral=True)
            return

        link = get_lodestone_link(person['id'])
        if not link:
            await interaction.response.send_message("No Lodestone account linked.", ephemeral=True)
            return

        add_scraper_task(link['lodestone_id'], priority=1)
        await interaction.response.send_message("Recheck task added to queue.", ephemeral=True)
        await asyncio.sleep(10)
        try:
            await interaction.delete_original_response()
        except discord.NotFound:
            pass


class DashboardButton(Button):
    def __init__(self) -> None:
        super().__init__(label="Dashboard", style=discord.ButtonStyle.secondary, custom_id="party_dashboard")

    async def callback(self, interaction: discord.Interaction) -> None:
        party_name = interaction.message.embeds[0].title.replace("Party: ", "")
        url = PersistentPartyView()._get_dashboard_url(party_name)
        await interaction.response.send_message(f"Dashboard: {url}", ephemeral=True)


class PersistentPartyView(View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(RecheckButton())
        self.add_item(DashboardButton())

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, custom_id="party_join")
    async def party_join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from app.db import add_person_to_party
        logging.info(f"Join button clicked by {interaction.user.display_name} (ID: {interaction.user.id})")
        party_name = interaction.message.embeds[0].title.replace("Party: ", "")
        add_person_to_party(interaction.user.display_name, party_name)
        logging.info(f"User {interaction.user.display_name} added to party {party_name}")
        await interaction.response.defer()
        await self.update_embed(interaction.channel, interaction.message)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, custom_id="party_leave")
    async def party_leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from app.db import remove_person_from_party
        logging.info(f"Leave button clicked by {interaction.user.display_name}")
        party_name = interaction.message.embeds[0].title.replace("Party: ", "")
        remove_person_from_party(interaction.user.display_name, party_name)
        logging.info(f"User {interaction.user.display_name} removed from party {party_name}")
        await interaction.response.defer()
        await self.update_embed(interaction.channel, interaction.message)

    @discord.ui.button(label="Set Jobs", style=discord.ButtonStyle.primary, custom_id="party_set_jobs")
    async def set_jobs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from bot.commands import MyJobsView, _load_person
        name = interaction.user.display_name
        current = _load_person(name)
        existing = current[0]["jobs"] if current else []
        view = MyJobsView(name, existing, interaction.user.id)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Move to Bottom", style=discord.ButtonStyle.secondary, custom_id="party_move_bottom")
    async def move_to_bottom(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        party_name = interaction.message.embeds[0].title.replace("Party: ", "")

        logging.info(f"Moving party {party_name} to bottom.")

        # Re-render the embed before moving to ensure it's up to date
        await self.update_embed(interaction.channel, interaction.message)

        # Now repost the message (the 'message' object is still the old one, we need to refresh it if it was edited)
        # However, update_embed edited it. We need the new version.

        # Actually, update_embed edits the message in place.
        # So interaction.message should now have the updated embed.

        # Repost
        view = PersistentPartyView()
        new_msg = await interaction.channel.send(embed=interaction.message.embeds[0], view=view)

        logging.info(f"Reposted message for party {party_name} as {new_msg.id}")

        # Delete old
        await interaction.message.delete()

        # Update DB
        try:
            party = Session.query(Party).filter_by(name=party_name).first()
            if party:
                party.home_channel_id = str(interaction.channel.id)
                party.home_message_id = str(new_msg.id)
                Session.commit()
        finally:
            Session.remove()

        logging.info(f"Updated DB for party {party_name} to channel {interaction.channel.id}, message {new_msg.id}")

        await interaction.response.defer()

    def _get_dashboard_url(self, party_name: str) -> str:
        base = os.environ.get("BASE_URL")
        if not base:
            raise RuntimeError("BASE_URL environment variable is not set.")
        # Dashboard is a SPA; we link to the party dashboard
        return f"{base.rstrip('/')}/party/{party_name}"

    async def update_embed(self, channel: discord.TextChannel, message: discord.Message) -> None:
        from app.db import constraints_from_db, get_cached_character, get_party_members

        # We need the party name. Can we extract it from the existing embed?
        party_name = message.embeds[0].title.replace("Party: ", "")

        members = get_party_members(party_name)
        logging.info(f"Updating embed for party {party_name}, members: {members}")
        constraints = constraints_from_db(party_name)
        target_ilvl = constraints.get("min_gear_level", 0)

        lines = []
        for m in members:
            # Fetch cached character data
            char_data = None
            if m['lodestone_id']:
                char_data = get_cached_character(m['lodestone_id'])

            line = f"**{m['name']}**"

            # Status Logic
            status = "Ready"
            if not m['lodestone_id']:
                status = "No Link"
            elif not char_data:
                status = "Loading"
            else:
                fetched_at = datetime.fromisoformat(char_data['fetched_at'])
                now = datetime.now(UTC)
                days_old = (now - fetched_at).days
                current_ilvl = char_data.get("avg_ilvl", 0)

                if days_old > 3:
                    status = f"Outdated ({days_old}d)"
                elif target_ilvl > 0 and current_ilvl < target_ilvl:
                    status = f"Low Gear ({current_ilvl}/{target_ilvl})"

            line += f" — {status}"

            if m['jobs']:
                line += f" ({_build_job_list(m['jobs'])})"
            else:
                line += " — Missing Jobs"

            lines.append(line)

        embed = discord.Embed(title=f"Party: {party_name}",
                              url=self._get_dashboard_url(party_name),
                              description="\n".join(lines) if lines else "No members.",
                              color=discord.Color.blue())

        logging.info(f"Editing message for party {party_name} with embed: {embed.description}")
        await message.edit(embed=embed, view=self)




@client.tree.command(name="setup-home-channel", description="Setup the persistent home channel embed for a party")
@app_commands.describe(party_name="The name of the party to set up")
@app_commands.checks.has_permissions(administrator=True)
async def setup_home_channel(interaction: discord.Interaction, party_name: str) -> None:
    # Check if party exists
    try:
        party = Session.query(Party).filter_by(name=party_name).first()
    finally:
        Session.remove()


    if not party:
        view = CreatePartyView(party_name)
        await interaction.response.send_message(f"Party '{party_name}' not found. Create it?", view=view, ephemeral=True)
        return

    await _perform_setup(interaction, party_name)


async def _perform_setup(interaction: discord.Interaction, party_name: str) -> None:
    channel = interaction.channel
    # Add the URL here too, for the initial message
    embed = discord.Embed(title=f"Party: {party_name}",
                          url=PersistentPartyView()._get_dashboard_url(party_name),
                          description="Manage your party status here.",
                          color=discord.Color.blue())
    view = PersistentPartyView()
    msg = await channel.send(embed=embed, view=view)

    try:
        party = Session.query(Party).filter_by(name=party_name).first()
        if party:
            party.home_channel_id = str(channel.id)
            party.home_message_id = str(msg.id)
            Session.commit()
    finally:
        Session.remove()

    # If this was called from a button, edit the original response
    if interaction.response.is_done():
        await interaction.followup.send(f"Home channel setup for {party_name}!", ephemeral=True)
    else:
        await interaction.response.send_message(f"Home channel setup for {party_name}!", ephemeral=True)


class CreatePartyView(View):
    def __init__(self, party_name: str) -> None:
        super().__init__(timeout=60)
        self.party_name = party_name

    @discord.ui.button(label="Create Party", style=discord.ButtonStyle.primary)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from app.db import create_party
        create_party(self.party_name)
        await _perform_setup(interaction, self.party_name)

