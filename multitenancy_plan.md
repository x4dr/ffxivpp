# Multi-Tenancy Refactor Plan

## 1. Database Schema Changes
- All tables must be scoped by `guild_id` (`TEXT`, non-nullable).
- **Tables to update:**
  - `parties`: Add `guild_id` (make `(guild_id, name)` the composite primary key).
  - `people`: Add `guild_id` (make `(guild_id, name)` the composite primary key).
  - `party_constraints`: Add `guild_id` (update PK to `(guild_id, party_name, key)`).
  - `party_exclusions`: Add `guild_id` (update query logic).
  - `party_people`: Add `guild_id` (update query logic).
  - `character_cache`: Include `guild_id`.
  - `scraper_tasks`: Add `guild_id`.
  - `admin_roles`: Already includes `guild_id`.
- **Database Optimization:** Create composite indexes for all new composite primary keys and frequently filtered columns (e.g., `CREATE INDEX idx_parties_guild ON parties(guild_id);`).

## 2. Authorization Layer (Critical Security)
- Implement authorization middleware to verify that the authenticated user has permission to access the requested `guild_id`.
- Prevent IDOR (Insecure Direct Object Reference) vulnerabilities: Validate ownership on every request that involves a `guild_id`.

## 3. Data Migration Strategy
- **Crucial:** Must backup the production DB before any schema changes.
- Strategy: Implement an **atomic** migration script.
- Rollback: Ensure a clear rollback procedure exists in case of failure.
- Integrity: Add validation checks (e.g., row counts, checksums) post-migration.

## 4. Session & Authentication Layer
- Upon OAuth login, determine the user's accessible guilds.
- Update `app/auth.py` and `app/routes.py` to store the *currently active* `guild_id` in the Flask `session`.
- UI: Add a "Guild Switcher" dropdown in the top-level dashboard if the user has access to multiple guilds.

## 5. Backend/API Layer Changes
- Update all functions in `app/db.py`:
  - Add `guild_id` argument to *all* functions.
  - Update all SQL queries to include `WHERE guild_id = ?`.
- Update `app/routes.py`:
  - Fetch `guild_id` from the session.
  - Ensure all routes pass the session `guild_id` to database functions.
- Observability: Update logging infrastructure to include `guild_id` as a structured field in all logs.

## 6. Bot Logic Changes
- Update `bot/commands.py`:
  - Every command must get `guild_id` from the discord interaction (`interaction.guild_id`).
  - Database calls in the bot must use this `guild_id`.
  - Remove all references to `os.environ.get("GUILD_ID")`.

## 7. Testing Strategy
- Create fixtures with multiple guilds to test data isolation.
- Add unit/integration tests that ensure:
  - Party A from Guild 1 is not visible in Guild 2.
  - Users from Guild 2 cannot modify constraints in Guild 1.

## 8. Deployment Plan
- Downtime is mandatory for DB migration.
- Backup, migrate schema, run data migration script, update app code, test, and restart.
