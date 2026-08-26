"""Questboard Discord commands, views, and the reminder loop.

Imported by bot/commands.py (after `client` exists) so the /quest command
group registers on the same CommandTree. DB access via core.questdb helpers;
tree math via core.quests. No emojis in embeds (docs convention).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands

from core import questdb
from core.quests import (
    NodeStatus,
    assign_node_ids,
    build_tree,
    flatten_requirements,
    node_statuses,
)

REMINDER_LOOP_INTERVAL = 30  # seconds between due-reminder scans


def _quest_tree_from_stored(tree_data: dict[str, Any]):
    root = build_tree(
        int(tree_data["item_id"]),
        str(tree_data["name"]),
        int(tree_data["qty_required"]),
        lambda _i: None,
        quality=str(tree_data.get("quality", "any")),
    )
    stack = [(root, tree_data.get("children", []))]
    while stack:
        parent, children = stack.pop()
        for child in children:
            node = build_tree(
                int(child["item_id"]),
                str(child["name"]),
                int(child["qty_required"]),
                lambda _i: None,
                quality=str(child.get("quality", "any")),
            )
            parent.children.append(node)
            if child.get("children"):
                stack.append((node, child["children"]))
    return root


def _status_line(s: NodeStatus) -> str:
    qty = f"x{s.required}"
    hq = " (HQ)" if s.quality == "hq" else ""
    if s.fulfilled:
        return f"{s.name} {qty}{hq} - done"
    pledged = f", {s.pledged} pledged" if s.pledged else ""
    return f"{s.name} {qty}{hq} - {s.outstanding} outstanding{pledged}"


def build_quest_embed(quest_id: int) -> discord.Embed | None:
    quest = questdb.get_quest(quest_id)
    if not quest:
        return None
    root = _quest_tree_from_stored(quest["tree"])
    assign_node_ids(root)
    pledges, turned = questdb.quest_amounts(quest_id)
    statuses = list(node_statuses(root, pledges, turned).values())
    shopping = flatten_requirements(root, pledges, turned)

    color = {
        "open": discord.Color.blurple(),
        "fulfilled": discord.Color.green(),
        "cancelled": discord.Color.dark_grey(),
    }.get(quest["status"], discord.Color.blurple())

    lines = [_status_line(s) for s in statuses[:20]]
    if len(statuses) > 20:
        lines.append(f"...and {len(statuses) - 20} more components")
    embed = discord.Embed(
        title=f"[{quest['status'].upper()}] {quest['title']}",
        description="\n".join(lines) or "No requirements.",
        color=color,
    )
    base_url = os.environ.get("BASE_URL", "").rstrip("/")
    if base_url:
        embed.url = f"{base_url}/quests/{quest_id}"
    if quest.get("deadline"):
        embed.add_field(name="Deadline", value=str(quest["deadline"]), inline=True)
    embed.add_field(
        name="Open materials",
        value=", ".join(f"{s.name} x{s.outstanding}" for s in shopping[:8]) or "none",
        inline=False,
    )
    embed.set_footer(text=f"Quest #{quest_id}")
    return embed


async def ensure_thread(client: discord.Client, quest_id: int) -> str | None:
    """Create the quest thread + status message once; returns thread id."""
    quest = questdb.get_quest(quest_id)
    if not quest:
        return None
    if quest.get("discord_thread_id") and quest.get("discord_message_id"):
        return str(quest["discord_thread_id"])

    home_channel_id = os.environ.get("QUESTBOARD_CHANNEL_ID")
    if not home_channel_id:
        logging.warning("QUESTBOARD_CHANNEL_ID not set; cannot create quest thread")
        return None
    channel = client.get_channel(int(home_channel_id))
    if not isinstance(channel, discord.TextChannel):
        logging.error("Questboard channel %s not found", home_channel_id)
        return None

    embed = build_quest_embed(quest_id)
    if embed is None:
        return None
    starter = await channel.send(embed=embed)
    thread_with_message = await channel.create_thread(
        name=f"[OPEN] {quest['title']}", message=starter
    )
    thread = thread_with_message
    message: discord.Message | None = starter

    from app.db import Session
    from core.questdb import Quest

    try:
        q = Session.query(Quest).filter_by(id=quest_id).first()
        if q:
            q.discord_thread_id = str(thread.id)
            if message:
                q.discord_message_id = str(message.id)
            Session.commit()
    finally:
        Session.remove()
    return str(thread.id)


class NodeSelect(discord.ui.Select):
    """Ingredient picker inside the contribute view."""

    def __init__(self, parent: QuestContributeView, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Choose what you want to provide...",
            options=options[:25],
        )
        self._parent_view = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        node_id = self.values[0]
        await interaction.response.send_modal(
            QuestPledgeModal(self._parent_view.quest_id, node_id)
        )


class QuestContributeView(discord.ui.View):
    """Ingredient picker + amount modal for pledging from Discord."""

    def __init__(self, quest_id: int, options: list[discord.SelectOption]) -> None:
        super().__init__(timeout=180)
        self.quest_id = quest_id
        self.add_item(NodeSelect(self, options))


class QuestPledgeModal(discord.ui.Modal, title="Pledge materials"):
    amount = discord.ui.TextInput(
        label="How many do you pledge?", placeholder="e.g. 500", max_length=9
    )

    def __init__(self, quest_id: int, node_id: str) -> None:
        super().__init__()
        self.quest_id = quest_id
        self.node_id = node_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).strip()
        if not raw.isdigit() or int(raw) < 1:
            await interaction.response.send_message(
                "Please enter a positive whole number.", ephemeral=True
            )
            return
        try:
            questdb.add_pledge(
                self.quest_id,
                self.node_id,
                str(interaction.user.id),
                int(raw),
                actor_id=str(interaction.user.id),
            )
        except KeyError as exc:
            await interaction.response.send_message(f"Unknown: {exc}", ephemeral=True)
            return
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer()
        await refresh_quest_message(interaction.client, self.quest_id)


async def refresh_quest_message(client_or_interaction: Any, quest_id: int) -> None:
    """Edit the quest thread's status embed after a change."""
    client = getattr(client_or_interaction, "client", client_or_interaction)
    quest = questdb.get_quest(quest_id)
    if not quest or not quest.get("discord_thread_id") or not quest.get("discord_message_id"):
        return
    channel = client.get_channel(int(quest["discord_thread_id"]))
    if channel is None:
        return
    try:
        message = await channel.fetch_message(int(quest["discord_message_id"]))
    except (discord.NotFound, discord.HTTPException):
        return
    embed = build_quest_embed(quest_id)
    if embed:
        try:
            await message.edit(embed=embed)
        except discord.HTTPException as exc:
            logging.error("quest embed edit failed: %s", exc)


def register_quest_commands(client: discord.Client) -> None:
    tree = client.tree

    @tree.command(name="quest-create", description="Open a new crafting quest")
    @app_commands.describe(title="Quest title", item="Item name (wiki lookup)", qty="Amount needed")
    async def quest_create(
        interaction: discord.Interaction, title: str, item: str, qty: int = 1
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        from core.wiki import lookup_recipe

        try:
            parsed = lookup_recipe(item)
            root_data = {"item_id": parsed.item_id, "name": parsed.name, "qty_required": qty}
        except Exception:  # noqa: BLE001 - wiki misses must not crash the command
            root_data = {"item_id": 0, "name": item, "qty_required": qty}
        root_data["children"] = []
        qid = questdb.create_quest(
            title=title,
            description="",
            created_by=str(interaction.user.id),
            root_tree=root_data,
        )
        thread_id = await ensure_thread(client, qid)
        tail = (
            f" Thread: <#{thread_id}>"
            if thread_id
            else " (Set QUESTBOARD_CHANNEL_ID for a thread.)"
        )
        msg = f"Quest #{qid} created." + tail
        await interaction.followup.send(msg, ephemeral=True)

    @tree.command(name="quest-list", description="List open quests")
    async def quest_list(interaction: discord.Interaction) -> None:
        quests = questdb.list_quests([questdb.QUEST_OPEN])
        if not quests:
            await interaction.response.send_message("No open quests.", ephemeral=True)
            return
        lines = [
            f"#{q['id']} — **{q['title']}**"
            + (f" (due {q['deadline']})" if q["deadline"] else "")
            for q in quests[:15]
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="quest-detail", description="Show a quest's requirement tree")
    @app_commands.describe(quest_id="Quest number")
    async def quest_detail(interaction: discord.Interaction, quest_id: int) -> None:
        quest = questdb.get_quest(quest_id)
        if not quest:
            await interaction.response.send_message("No such quest.", ephemeral=True)
            return
        embed = build_quest_embed(quest_id)
        if embed is None:
            await interaction.response.send_message("Could not render quest.", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="quest-contribute", description="Pledge items for a quest")
    @app_commands.describe(quest_id="Quest number")
    async def quest_contribute(interaction: discord.Interaction, quest_id: int) -> None:
        quest = questdb.get_quest(quest_id)
        if not quest or quest["status"] != questdb.QUEST_OPEN:
            await interaction.response.send_message(
                "That quest is not open.", ephemeral=True
            )
            return
        root = _quest_tree_from_stored(quest["tree"])
        assign_node_ids(root)
        pledges, turned = questdb.quest_amounts(quest_id)
        open_nodes = [s for s in node_statuses(root, pledges, turned).values() if not s.fulfilled]
        if not open_nodes:
            await interaction.response.send_message("Everything is covered!", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=f"{s.name} ({s.open_to_pledge} needed)", value=s.node_id)
            for s in open_nodes[:25]
        ]
        await interaction.response.send_message(
            "What can you bring?",
            view=QuestContributeView(quest_id, options),
            ephemeral=True,
        )

    @tree.command(name="quest-close", description="Close a quest (officer)")
    @app_commands.describe(quest_id="Quest number", status="New status")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="fulfilled", value="fulfilled"),
            app_commands.Choice(name="cancelled", value="cancelled"),
            app_commands.Choice(name="open", value="open"),
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def quest_close(
        interaction: discord.Interaction, quest_id: int, status: app_commands.Choice[str]
    ) -> None:
        ok = questdb.set_quest_status(quest_id, status.value, str(interaction.user.id))
        if not ok:
            await interaction.response.send_message("No such quest.", ephemeral=True)
            return
        await refresh_quest_message(client, quest_id)
        await interaction.response.send_message(
            f"Quest #{quest_id} -> {status.value}.", ephemeral=True
        )

    @tree.command(name="quest-remind-me", description="Get reminders about your open pledges")
    @app_commands.describe(
        quest_id="Quest number",
        frequency="daily or weekly",
        time_utc="Time of day, HH:MM in UTC",
        weekday="For weekly: Monday..Sunday",
    )
    @app_commands.choices(
        weekday=[app_commands.Choice(name=d, value=i) for i, d in enumerate(
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        )]
    )
    async def quest_remind_me(
        interaction: discord.Interaction,
        quest_id: int,
        frequency: str,
        time_utc: str,
        weekday: app_commands.Choice[int] | None = None,
    ) -> None:
        try:
            hour, minute = (int(p) for p in time_utc.split(":"))
            kwargs: dict[str, Any] = {}
            if weekday is not None:
                kwargs["weekday_utc"] = weekday.value
            questdb.upsert_reminder_optin(
                quest_id, str(interaction.user.id), frequency, hour, minute, **kwargs
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Reminders set: {frequency} at {time_utc} UTC while you have open pledges.",
            ephemeral=True,
        )


async def reminder_loop(client: discord.Client) -> None:
    """Scan due reminder opt-ins; DM users with open pledges."""
    await asyncio.sleep(15)
    logging.info("Questboard reminder loop started.")
    while not client.is_closed():
        try:
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            for entry in questdb.due_reminders(now):
                user = await _safe_fetch_user(client, entry["person_id"])
                if not user:
                    continue
                quest = questdb.get_quest(entry["quest_id"])
                if not quest or quest["status"] != questdb.QUEST_OPEN:
                    continue
                root = _quest_tree_from_stored(quest["tree"])
                assign_node_ids(root)
                my_open = [
                    p
                    for p in _raw_pledges(entry["quest_id"])
                    if p.person_id == entry["person_id"]
                    and not p.withdrawn
                    and p.turned_qty < p.qty
                ]
                if not my_open:
                    continue
                lines = [
                    f"**{p.qty - p.turned_qty}x still owed** (node {p.node_id})"
                    for p in my_open
                ]
                try:
                    base = os.environ.get("BASE_URL", "").rstrip("/")
                    await user.send(
                        f"Quest '{quest['title']}' reminder:\n" + "\n".join(lines)
                        + f"\n\nDetails: {base}/quests/{entry['quest_id']}"
                    )
                except discord.HTTPException:
                    logging.info("could not DM %s", entry["person_id"])
        except Exception:  # noqa: BLE001 - the loop must survive anything
            logging.exception("reminder loop iteration failed")
        await asyncio.sleep(REMINDER_LOOP_INTERVAL)


def _raw_pledges(quest_id: int):
    from app.db import Session
    from core.questdb import QuestPledge

    try:
        return Session.query(QuestPledge).filter_by(quest_id=quest_id).all()
    finally:
        Session.remove()


async def _safe_fetch_user(client: discord.Client, user_id: str):
    try:
        return await client.fetch_user(int(user_id))
    except (discord.HTTPException, ValueError):
        return None


_ = json  # json kept imported for future event payload rendering
