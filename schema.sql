CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  jobs TEXT NOT NULL,
  discord_id TEXT
);

CREATE TABLE IF NOT EXISTS constraint_config (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO constraint_config (id, value) VALUES
  ('std_comp', 'true'),
  ('no_dupes', 'true'),
  ('heal_mix', 'false'),
  ('max_melee', '4'),
  ('max_pranged', '4'),
  ('max_caster', '4'),
  ('min_melee', '0'),
  ('min_pranged', '0'),
  ('min_caster', '0'),
  ('min_selfish', '0'),
  ('max_selfish', '4'),
  ('min_utility', '0'),
  ('max_utility', '4');

CREATE TABLE IF NOT EXISTS admin_roles (
  guild_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS exclusions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  jobs TEXT NOT NULL
);
