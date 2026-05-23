"""FF14 Party Planner — Discord bot commands."""

# mypy: ignore-errors
# discord.py UI component stubs are incomplete (parent property, generics)

from __future__ import annotations

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import os
import re
import asyncio
import sqlite3
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from app.compute import JOBS, JOBS_BY_ID, get_priority, parse_job_id
from app.db import (
    add_role_id,
    get_role_ids,
    remove_role_id,
)
from discord import app_commands
from discord.ui import Button, Select, View

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
        self.add_view(PersistentPartyView())
        guild_id = os.environ.get("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            await self.tree.sync()
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.loop.create_task(self.scraper_loop())

    async def scraper_loop(self) -> None:
        """Background loop to refresh character data with optimized DB locking."""
        from app.db import db_connection, update_lodestone_fetched_at, set_lodestone_link
        from app.lodestone import fetch_character
        import sqlite3
        import random

        loop = asyncio.get_event_loop()
        await asyncio.sleep(10)
        logging.info("Scraper loop started.")
        
        while not self.is_closed():
            try:
                # 1. READ: Get ID using context manager
                person_id = None
                lodestone_id = None
                with db_connection() as db:
                    row = db.execute(
                        "SELECT person_id, lodestone_id FROM lodestone_links ORDER BY fetched_at ASC LIMIT 1"
                    ).fetchone()
                    person_id = row['person_id'] if row else None
                    lodestone_id = row['lodestone_id'] if row else None
                
                if lodestone_id:
                    logging.info(f"Scraping {lodestone_id}...")
                    # 2. NETWORK IO: Run without holding any DB lock
                    data = await loop.run_in_executor(None, fetch_character, lodestone_id)
                    
                    # 3. WRITE: Open only when needed using context manager
                    if data and "name" in data:
                        update_lodestone_fetched_at(lodestone_id)
                        set_lodestone_link(person_id, lodestone_id, data["name"])
                        
                    logging.info(f"Finished scraping {lodestone_id}.")
            except sqlite3.OperationalError as e:

                if "locked" in str(e).lower():
                    wait = random.uniform(2, 10)
                    logging.warning(f"Database locked, retrying in {wait:.2f}s...")
                    await asyncio.sleep(wait)
                    continue
                else:
                    logging.error(f"Database error: {e}")
            except Exception as e:
                logging.error(f"Scraper error: {e}")
            await asyncio.sleep(10)



    async def on_ready(self) -> None:
        print(f"Bot logged in as {self.user}")
        self.add_view(PersistentPartyView())
        if self.application and self.application.owner:
            owner_id = str(self.application.owner.id)
            from app.db import db_connection

            with db_connection() as db:
                db.execute(
                    "INSERT OR REPLACE INTO app_state (key, value) VALUES ('bot_owner_id', ?)",
                    (owner_id,),
                )
                db.commit()
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
    from app.db import db_connection, people_pool, pool_save

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
        with db_connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO party_people (party_name, person_name) VALUES ('Default', ?)",
                (name,),
            )
            db.commit()


def _build_job_list(jobs: list[str]) -> str:
    parts: list[str] = []
    for entry in jobs:
        jid = parse_job_id(entry)
        prio = get_priority(entry)
        name = JOB_NAMES.get(jid, jid.upper())
        parts.append(f"{name}[{prio}]")
    return ", ".join(parts) if parts else "*none*"


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

    from app.db import get_db, close_db, set_lodestone_link
    from app.lodestone import fetch_character

    data = fetch_character(lodestone_id)
    if "error" in data:
        await interaction.followup.send(data["error"], ephemeral=True)
        return

    # Find the person_id by discord_id
    db = get_db()
    row = db.execute("SELECT id FROM people WHERE discord_id = ?", (str(interaction.user.id),)).fetchone()
    close_db(conn=db)
    
    if not row:
        await interaction.followup.send("Could not find a linked person for your Discord account.", ephemeral=True)
        return
        
    person_id = row['id']
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


class PersistentPartyView(View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(Button(label="Join", style=discord.ButtonStyle.success, custom_id="party_join"))
        self.add_item(Button(label="Leave", style=discord.ButtonStyle.danger, custom_id="party_leave"))
        self.add_item(Button(label="Dashboard", style=discord.ButtonStyle.link, url=os.environ.get("BASE_URL", "http://localhost:5000")))

    async def update_embed(self, channel: discord.TextChannel, message: discord.Message) -> None:
        from app.db import get_party_members
        
        # We need the party name. Can we extract it from the existing embed?
        party_name = message.embeds[0].title.replace("Party: ", "")
        
        members = get_party_members(party_name)
        
        lines = []
        for m in members:
            line = f"**{m['name']}**"
            if not m['jobs']:
                line += " — ⚠️ Missing Jobs"
            
            if not m['lodestone_id']:
                line += " — ⚠️ Missing Lodestone"
            else:
                fetched_at = m['fetched_at']
                if not fetched_at:
                    line += " — ⚠️ No Data"
                else:
                    ts = datetime.fromisoformat(fetched_at)
                    if datetime.now(timezone.utc) - ts > timedelta(days=7):
                        line += " — ⚠️ Outdated Data"
            lines.append(line)
        
        embed = discord.Embed(title=f"Party: {party_name}", 
                              description="\n".join(lines) if lines else "No members.", 
                              color=discord.Color.blue())
        
        await message.edit(embed=embed, view=self)


@client.tree.command(name="setup-home-channel", description="Setup the persistent home channel embed for a party")
@app_commands.describe(party_name="The name of the party to set up")
@app_commands.checks.has_permissions(administrator=True)
async def setup_home_channel(interaction: discord.Interaction, party_name: str) -> None:
    from app.db import db_connection
    
    # Check if party exists
    with db_connection() as db:
        party = db.execute("SELECT name FROM parties WHERE name = ?", (party_name,)).fetchone()
        if not party:
            await interaction.response.send_message(f"Party '{party_name}' not found.", ephemeral=True)
            return

    channel = interaction.channel
    embed = discord.Embed(title=f"Party: {party_name}", description="Manage your party status here.", color=discord.Color.blue())
    view = PersistentPartyView()
    msg = await channel.send(embed=embed, view=view)
    
    with db_connection() as db:
        db.execute("UPDATE parties SET home_channel_id = ?, home_message_id = ? WHERE name = ?", 
                   (str(channel.id), str(msg.id), party_name))
        db.commit()
    
    await interaction.response.send_message(f"Home channel setup for {party_name}!", ephemeral=True)

