"""FF14 Party Planner — Discord bot."""

from __future__ import annotations

import os

import discord
from discord import app_commands

from app import (
    JOBS,
    Constraints,
    Person,
    _constraints_from_db,
    _people_from_db,
    _people_to_db,
    compute_parties,
)

VALID_JOBS = {j.id for j in JOBS}
JOB_NAMES = {j.id: j.name for j in JOBS}
MAX_SHOWN = 5


def _parse_jobs(s: str) -> list[str]:
    return [j.strip().lower() for j in s.split(",") if j.strip().lower() in VALID_JOBS]


class PartyBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()


client = PartyBot()


@client.tree.command(name="setjobs", description="Set a member's available jobs (admin only)")
@app_commands.describe(member="The server member", jobs="Comma-separated job IDs, e.g. pld,drk,vpr")
@app_commands.checks.has_permissions(administrator=True)
async def setjobs(interaction: discord.Interaction, member: discord.Member, jobs: str) -> None:
    jids = _parse_jobs(jobs)
    if not jids:
        await interaction.response.send_message(
            f"No valid jobs. IDs: `{', '.join(sorted(VALID_JOBS))}`", ephemeral=True
        )
        return
    name = member.display_name
    current = _people_from_db()
    filtered = [p for p in current if p["name"] != name]
    filtered.append({"name": name, "jobs": jids})
    _people_to_db(filtered)
    names = ", ".join(JOB_NAMES[j].upper() for j in jids)
    await interaction.response.send_message(
        f"Set {member.mention}'s jobs: {names}", ephemeral=True
    )


@client.tree.command(name="myjobs", description="Set your own available jobs")
@app_commands.describe(jobs="Comma-separated job IDs, e.g. pld,drk,vpr")
async def myjobs(interaction: discord.Interaction, jobs: str) -> None:
    jids = _parse_jobs(jobs)
    if not jids:
        await interaction.response.send_message(
            f"No valid jobs. IDs: `{', '.join(sorted(VALID_JOBS))}`", ephemeral=True
        )
        return
    name = interaction.user.display_name
    current = _people_from_db()
    filtered = [p for p in current if p["name"] != name]
    filtered.append({"name": name, "jobs": jids})
    _people_to_db(filtered)
    names = ", ".join(JOB_NAMES[j].upper() for j in jids)
    await interaction.response.send_message(f"Your jobs saved: {names}", ephemeral=True)


@client.tree.command(name="parties", description="Compute valid party combinations")
async def parties(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    raw = _people_from_db()
    if not raw:
        await interaction.followup.send("No people configured yet. Use `/setjobs` or `/myjobs`.")
        return
    people = [Person(p["name"], p["jobs"]) for p in raw]
    c = Constraints.from_dict(_constraints_from_db())
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


@client.tree.command(name="constraints", description="Show current constraints")
async def show_constraints(interaction: discord.Interaction) -> None:
    c = Constraints.from_dict(_constraints_from_db())
    lines = [
        f"Standard comp (2/2/4): {'✅' if c.std_comp else '❌'}",
        f"No duplicate jobs: {'✅' if c.no_dupes else '❌'}",
        f"Pure + shield healer: {'✅' if c.heal_mix else '❌'}",
        f"Melee: {c.min_melee}-{c.max_melee}"
        f"  Ranged: {c.min_pranged}-{c.max_pranged}"
        f"  Caster: {c.min_caster}-{c.max_caster}",
    ]
    await interaction.response.send_message("**Constraints**\n" + "\n".join(lines), ephemeral=True)


@client.tree.command(name="roster", description="Show everyone's saved job pools")
async def roster(interaction: discord.Interaction) -> None:
    people = _people_from_db()
    if not people:
        await interaction.response.send_message("No people configured yet.", ephemeral=True)
        return
    lines = [f"**Roster ({len(people)} people)**"]
    for p in people:
        jobs = [JOB_NAMES.get(j, j.upper()) for j in p["jobs"]]
        lines.append(f"**{p['name']}**: {', '.join(jobs) if jobs else '*none*'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


def main() -> None:
    load_dotenv()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN environment variable")
    client.run(token)


if __name__ == "__main__":
    main()
