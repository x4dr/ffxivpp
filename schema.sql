CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  jobs TEXT NOT NULL
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
  ('min_caster', '0');