# FF14 Party Planner — Project Outline

## Phase 1 — Core (done)

- [x] SQLite-backed roster (people + job pools)
- [x] Constraint system (std comp 2/2/4, no duplicate jobs, heal mix, DPS subrole ranges)
- [x] DFS party computation (exhaustive, respects all constraints)
- [x] Admin web UI — manual JSON input, constraint toggles, results viewer with export
- [x] Discord bot — `/setjobs`, `/myjobs`, `/parties`, `/constraints`, `/roster`

## Phase 2 — Discord Auth & Admin Access (next)

- Discord OAuth2 login on the admin site (using `identify` + `guilds` scopes)
- Access control: server admins always allowed + configurable role whitelist (set via slash command `/admin_role`)
- Web UI reads people directly from Discord roster (no manual JSON)
- Admin can pick a target channel for party results / polls

## Phase 3 — Polling & Party Selection

- Discord native poll support — bot creates a poll with party options
  - discord.py 2.3+ has `discord.Poll` (question text, multiple answers with optional emoji, single/multi choice, auto-close timer)
  - Alternative: simple reaction-based polls (numbered emoji per party)
- Admin triggers `/partypoll` or selects from web UI → posts poll to target channel
- Results tallied, winning party posted

## Phase 4 — Lodestone / Crafting Organizer (rough, deferred)

- Look up character profiles via FFXIV API (Lodestone / XIVAPI)
- Detect job levels, gear, missing best-in-slot pieces
- Track what needs to be crafted per member
- Dashboard on the website
- Discord slash commands:
  - `/demands` — list open crafting/resource demands
  - `/take` — claim a demand (marks your name, logs to a designated channel)
- Avoids duplication of effort in the guild
