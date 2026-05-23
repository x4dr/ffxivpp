"""FF14 Party Planner — Discord bot commands."""

# mypy: ignore-errors
# discord.py UI component stubs are incomplete (parent property, generics)

from __future__ import annotations

import os
from typing import Any

import discord
from discord import app_commands
from discord.ui import Button, Select, View

from app.compute import JOBS, JOBS_BY_ID, compute_parties, get_priority, parse_job_id
from app.db import (
    add_role_id,
    constraints_from_db,
    get_role_ids,
    people_from_db,
    remove_role_id,
)
from app.models import Constraints, Person

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

MAX_SHOWN = 5


def parse_jobs(s: str) -> list[str]:
    import re
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
        guild_id = os.environ.get("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            await self.tree.sync()
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Bot logged in as {self.user}")


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
    from app.db import get_db, people_pool, pool_save

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
        get_db().execute(
            "INSERT OR IGNORE INTO party_people (party_name, person_name) VALUES ('Default', ?)",
            (name,),
        )
        get_db().commit()


def _build_job_list(jobs: list[str]) -> str:
    parts: list[str] = []
    for entry in jobs:
        jid = parse_job_id(entry)
        prio = get_priority(entry)
        name = JOB_NAMES.get(jid, jid.upper())
        parts.append(f"{name}[{prio}]")
    return ", ".join(parts) if parts else "*none*"


# ── /setjobs ────────────────────────────────────────────────────────────


@client.tree.command(name="setjobs", description="Set a member's available jobs (admin only)")
@app_commands.describe(member="The server member", jobs="Comma-separated job IDs, e.g. pld,drk,vpr")
@app_commands.checks.has_permissions(administrator=True)
async def setjobs(interaction: discord.Interaction, member: discord.Member, jobs: str) -> None:
    jids = parse_jobs(jobs)
    if not jids:
        await interaction.response.send_message(
            f"No valid jobs. IDs: `{', '.join(sorted(VALID_JOBS))}`", ephemeral=True
        )
        return
    discord_id = str(member.id) if not member.bot else None
    _save_person(member.display_name, jids, discord_id)
    await interaction.response.send_message(
        f"Set {member.mention}'s jobs: {_build_job_list(jids)}", ephemeral=True
    )


# ── /myjobs (interactive UI) ────────────────────────────────────────────


@client.tree.command(name="myjobs", description="Set your own available jobs")
async def myjobs(interaction: discord.Interaction) -> None:
    name = interaction.user.display_name
    current = _load_person(name)
    existing = current[0]["jobs"] if current else []
    view = MyJobsView(name, existing, interaction.user.id)
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


class MyJobsView(View):
    def __init__(self, name: str, jobs: list[str], user_id: int) -> None:
        super().__init__(timeout=300)
        self.name = name
        self.jobs: list[tuple[str, int]] = [
            (parse_job_id(e), get_priority(e)) for e in jobs
        ]
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
            added = 0
            for jid in ROLE_JOBS[role]:
                if not any(j == jid for j, _ in self._main_view.jobs):
                    self._main_view.jobs.append((jid, 5))
                    added += 1
            self._main_view._save()
            self._main_view._build()
            await interaction.response.edit_message(
                embed=self._main_view.build_embed(), view=self._main_view
            )
            return
        role = val
        jobs_for_role = ROLE_JOBS[role]
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
        await interaction.response.edit_message(
            embed=self._main_view.build_embed(), view=self._main_view
        )


class JobAdjustSelect(Select):
    def __init__(self, parent: MyJobsView) -> None:
        opts = [
            discord.SelectOption(
                label=f"{JOB_NAMES.get(jid, jid.upper())} [prio {prio}]",
                value=f"{jid}:{prio}",
            )
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
            self._main_view.jobs = [
                (j, new_prio if j == self.jid else p)
                for j, p in self._main_view.jobs
            ]
        self._main_view._save()
        self._main_view._build()
        await interaction.response.edit_message(
            embed=self._main_view.build_embed(), view=self._main_view
        )


# ── /parties ────────────────────────────────────────────────────────────


@client.tree.command(name="parties", description="Compute valid party combinations")
async def parties(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    raw = people_from_db()
    if not raw:
        await interaction.followup.send("No people configured yet. Use `/setjobs` or `/myjobs`.")
        return
    people = [Person(p["name"], p["jobs"]) for p in raw]
    c = Constraints.from_dict(constraints_from_db())
    results = compute_parties(people, c)
    if not results:
        await interaction.followup.send("No valid parties with current constraints.")
        return
    count = len(results)
    lines = [f"**{count:,} valid party combinations**", ""]
    for i, party in enumerate(results[:MAX_SHOWN]):
        parts = [f"{a.name}:{a.job}" for a in party]
        lines.append(f"`Party {i + 1:>2}`  {', '.join(parts)}")
    if count > MAX_SHOWN:
        lines.append(f"\n*... and {count - MAX_SHOWN:,} more. Visit /admin for full list.*")
    await interaction.followup.send("\n".join(lines))


# ── /constraints ────────────────────────────────────────────────────────


@client.tree.command(name="constraints", description="Show current constraints")
async def show_constraints(interaction: discord.Interaction) -> None:
    c = Constraints.from_dict(constraints_from_db())
    excl_strs = [",".join(g).upper() for g in c.exclusions] if c.exclusions else []
    lines = [
        f"Standard comp (2/2/4): {'✅' if c.std_comp else '❌'}",
        f"No duplicate jobs: {'✅' if c.no_dupes else '❌'}",
        f"Pure + shield healer: {'✅' if c.heal_mix else '❌'}",
        f"Melee: {c.min_melee}-{c.max_melee}"
        f"  Ranged: {c.min_pranged}-{c.max_pranged}"
        f"  Caster: {c.min_caster}-{c.max_caster}",
        f"Selfish DPS: {c.min_selfish}-{c.max_selfish}"
        f"  Utility DPS: {c.min_utility}-{c.max_utility}",
        f"Exclusions: {', '.join(excl_strs) if excl_strs else 'none'}",
    ]
    await interaction.response.send_message("**Constraints**\n" + "\n".join(lines), ephemeral=True)


# ── /roster ─────────────────────────────────────────────────────────────


@client.tree.command(name="roster", description="Show everyone's saved job pools")
async def roster(interaction: discord.Interaction) -> None:
    people = people_from_db()
    if not people:
        await interaction.response.send_message("No people configured yet.", ephemeral=True)
        return
    embed = discord.Embed(title=f"Roster ({len(people)} people)", color=discord.Color.blue())
    for p in people:
        val = _build_job_list(p["jobs"])
        embed.add_field(name=p["name"], value=val, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


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


@client.tree.command(
    name="admin-role-remove", description="Remove a role from admin panel whitelist"
)
@app_commands.describe(role="Role to remove from whitelist")
@app_commands.checks.has_permissions(administrator=True)
async def admin_role_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    guild_id = str(interaction.guild_id)
    remove_role_id(guild_id, str(role.id))
    await interaction.response.send_message(
        f"Removed {role.mention} from the admin panel whitelist.", ephemeral=True
    )


@client.tree.command(name="admin-role-list", description="List whitelisted admin roles")
async def admin_role_list(interaction: discord.Interaction) -> None:
    guild_id = str(interaction.guild_id)
    role_ids = get_role_ids(guild_id)
    if not role_ids:
        await interaction.response.send_message(
            "No roles whitelisted yet. Server admins can use `/admin-role-add` to add roles.",
            ephemeral=True,
        )
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message(
            "This command must be used in a server.", ephemeral=True
        )
        return
    names: list[str] = []
    for rid in role_ids:
        role = guild.get_role(int(rid))
        names.append(role.mention if role else f"`{rid}`")
    await interaction.response.send_message(
        f"**Whitelisted admin roles:** {', '.join(names)}", ephemeral=True
    )
