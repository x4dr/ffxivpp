# Implementation Plan: Persistent Party Home Channel

## Objective
Implement a functional, interactive persistent Discord embed that displays party member status and allows for member management directly from Discord.

## Design Constraints & Notes
- **Absolutely minimize DB lock time**: Open/close connections immediately; NEVER hold a DB connection during network I/O.
- **Scraper Safety**:
    - Use a `scraper_tasks` table.
    - Tasks are deleted upon completion.
    - If a `lodestone_id` is already in `scraper_tasks`, skip adding it.
    - The scraper processes high-priority tasks as fast as safely possible (rate-limited, e.g., 1 req/sec).
- **Embed Logic**: Trigger `update_embed` immediately after a successful scrape update.
- **Visuals (No Emojis)**:
    - **Outdated**: `Outdated (X days)` if >3 days AND gear doesn't meet target.
    - **Low Gear**: `Low Gear (Current: X / Target: Y)` if <3 days AND gear is too low.
    - **Missing Data**: `[no data]`
    - **Note**: Assume gear level never goes down for a specific job.

## Phase 1: Infrastructure & DB Schema
- [ ] Add `scraper_tasks` table (`lodestone_id`, `priority`, `created_at`).
- [ ] Create DB helper functions for `scraper_tasks` (add_task, get_next_task, delete_task).
- [ ] Ensure all existing DB interaction points strictly follow the "open/close immediately" rule.

## Phase 2: Embed Refresh & Member Status (Enhanced)
- [ ] Implement `update_embed` in `PersistentPartyView` to:
    - Query party members from DB.
    - Check for missing jobs/Lodestone.
    - Validate Lodestone data age (older than 3 days = Outdated IF gear too low).
    - Compare cached gear level against party's `min_gear_level` (for display/warning only).
    - Format status lines (no emojis).
- [ ] Add "Recheck Lodestone" button for members who failed checks.
- [ ] Implement `interaction_check` to handle the buttons (Refresh, Recheck).

## Phase 3: Web UI & Admin Rework
- [ ] Update `app/models.py` to add `min_gear_level` as a party property (not a hard constraint).
- [ ] Update `app/db.py` logic to save `min_gear_level`.
- [ ] Update `static/admin.html` to allow configuring `min_gear_level` for a party.
- [ ] Update party details handler to support updating `min_gear_level`.

## Phase 4: Action Buttons
- [ ] Add buttons to `PersistentPartyView`:
    - **Set Jobs**: Trigger interactive `MyJobsView`.
    - **Set Lodestone**: Open a Modal for URL input.
    - **Re-request**: Trigger high-priority scraper queue for a specific user (linked to "Recheck Lodestone").

## Phase 5: Prioritized Scraper Queue & Dynamic Delay
- [ ] Implement `scraper_loop` in `PartyBot`:
    - Check `scraper_tasks` for high-priority items.
    - If empty, pull from standard refresh queue.
    - Process tasks as fast as safely possible (e.g., 1 sec delay for priority).
    - After DB update, explicitly call `update_embed` for the relevant party (requires tracking channel/message IDs).

## Phase 6: Testing
- [ ] Add unit tests for `scraper_loop` priority logic (mocking DB and network).
- [ ] Add unit tests for embed status string generation logic.
- [ ] Add unit tests for DB connection handling to verify no locks are held during I/O.

## Deliverables
1. `scraper_tasks` table and helpers.
2. Updated `bot/commands.py` with `PersistentPartyView` and recheck logic.
3. Updated Web UI/DB schema.
4. Robust `PartyBot.scraper_loop`.
5. Comprehensive test suite.
