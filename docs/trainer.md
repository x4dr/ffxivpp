# Keybind trainer

Drills the abilities on your own hotbars as flashcards: it shows an ability,
you press the combo that FFXIV has bound to it, and it times you and classifies
the miss.

- `/trainer/` is public. No Discord login is needed to train.
- Anonymous use stays in the browser: the `.DAT` files are read in the page with
  the File API, parsed in JavaScript, and never sent anywhere.
- Signing in is optional. It exists to save the files and the history to your
  Discord account, so another machine can pick them up and the weighting can
  learn from more than one browser.

## Data flow

```
KEYBIND.DAT ─┐
             ├─► parsed in the page ─► cards ─► verdicts ─► localStorage
HOTBAR.DAT  ─┘                                          │
                                                        │  "Save to account"
                                                        ▼
                                              POST /trainer/api/save
                                                        │
                                              data/trainer.db (by user id)
```

The server is not in the training loop. It serves the page and the bundled
indices, proxies icons, and stores a user's own copy when asked.

### Anonymous

Everything lives under the `ffxivtrainer.` prefix in `localStorage`:

| key | contents |
| --- | --- |
| `keybind` / `hotbar` | the uploaded bytes, base64, plus the file name |
| `selection` | ticked bars per job block |
| `order` | bar display order per job block |
| `taught` | bind name to browser key code, for ids the importer cannot name |
| `sessions` | finished sessions with their attempts, at most 200 |
| `lastCard` | the scorecard of the most recent session |
| `remoteStats` / `remoteBaseline` / `remoteSavedAt` | the account copy, after a load or save |

Losing the browser storage loses the anonymous history. That is the trade for
not sending the files anywhere.

### Signed in

Saving and loading are explicit buttons in the header. Nothing is uploaded by
merely logging in.

- **Save to account** sends the raw `.DAT` files (only if present), the bar
  selection, order, the selected job, taught keys, and every unsynced session.
  After a successful save the local session list is cleared; the server returns
  the aggregate counters that the weighting needs.
- **Load from account** replaces the browser's binds and hotbar with the saved
  copy, keeps any unsynced local sessions, and pulls the aggregate counters and
  the last session's scorecard.

Sessions carry a `client_id` from the browser. The store has a
`UNIQUE (user_id, client_id)` constraint, so retrying a save after a dropped
connection cannot double-count attempts.

## Server surface

| route | purpose |
| --- | --- |
| `GET /trainer/`, `/trainer/binds`, `/trainer/hotbars`, `/trainer/train`, `/trainer/score` | the SPA shell; every view is a real path |
| `GET /trainer/api/state` | the signed-in user's saved copy, counters and last session; `401` when anonymous |
| `POST /trainer/api/save` | store files, choices and sessions for the signed-in user |
| `GET /trainer/api/icon/<action_id>` | action icon via xivapi, disk-cached |
| `GET /trainer/api/item-icon/<item_id>` | item icon via XIVAPI v2, disk-cached |

Storage is a separate SQLite file, `data/trainer.db` by default
(`TRAINER_DB_PATH` overrides it), so trainer writes never go through the
party/quest database. One row per Discord user in `profiles`; `sessions` and
`attempts` are keyed by the same user id. `app/trainer/store.py` is the only
module that reads or writes it.

Upload limits: 2 MB per `.DAT` file, 200 sessions and 5,000 attempts per save,
1,000 attempts per session. Files are type-checked by their first four bytes,
so a `HOTBAR.DAT` cannot be stored in the `KEYBIND.DAT` slot.

Icons are the only thing the browser asks the server for that is not the page
or the bundled data. They are public game art, not personal data. Both xivapi
hosts send `access-control-allow-origin: *`, so this could move into the
browser, but proxying keeps one cache and avoids a second storage layer.

## Data files and tools

| path | what it is |
| --- | --- |
| `static/trainer/js/` | parsers, catalog, weighting and scoring, UI |
| `static/trainer/data/action_index.json` | action id to name, bundled from the plugin's sheet dump |
| `static/trainer/data/item_index.json` | item id to name and icon path |
| `static/trainer/data/job_index.json` | ClassJob row id to abbreviation and name |
| `data/trainer/icon_cache/` | proxied icons and `.missing` markers; not in git |
| `tools/trainer/build_action_index.py` | rebuild the action index from the plugin dumps |
| `tools/trainer/resolve_items.mjs` | resolve item slots in a `HOTBAR.DAT` through XIVAPI v2 |
| `tools/trainer/HotbarDump/` | Dalamud plugin: ground truth from the running client |
| `tools/trainer/probe/` | reflection probe for Dalamud/Lumina/FFXIVClientStructs |

Formats and the verified facts behind them are in
[`trainer-data-formats.md`](trainer-data-formats.md).

## Tests

```sh
uv run pytest tests/test_trainer_api.py tests/test_trainer_store.py tests/test_auth_next.py
node --test tests/js/
```

`tests/test_js.py` runs the JavaScript suite through pytest and skips when node
is not installed. The JS tests build synthetic containers and also assert
against the real files under `~/.xlcore/ffxivConfig` when they exist; those
expectations are values read out of the running game, not a restatement of what
the parser happens to produce.

## Deployment

No new Python dependency and no new service. The trainer is a blueprint on the
existing Flask app, plus static files.

- The store writes `data/trainer.db`; the service user needs write access to
  `data/`. `TRAINER_DB_PATH` moves it, `TRAINER_DATA_DIR` moves the icon cache.
- `deploy/nginx.conf` raises `client_max_body_size` to 8 MB (account saves carry
  base64 `.DAT` files) and enables gzip for JS/JSON/CSS. Reload nginx after
  deploying it; the defaults are 1 MB and no compression for those types.
- Restarting the Flask app is enough to publish the code. No migration step:
  the store creates its tables on first use and adds new profile columns in
  `store.init()`.

## Differences from the prototype

The first version was a throwaway FastAPI app in `~/tmp`; the port deliberately
changes three things:

- **The baseline is the median it always claimed to be.** The prototype's
  `baseline()` docstring said median and its SQL computed `AVG`. The JavaScript
  uses the median of correct latencies, with the same 150 ms floor and 700 ms
  fallback.
- **A taught key becomes trainable.** The prototype stored the code taught for
  an unknown key id but left `trainable = 0`, so a bind that had just been
  taught was still never drawn.
- **Bar order is kept.** The prototype's UI posted an `order` field that its
  request model silently ignored. Order is now local UI state and is saved with
  the account copy.

## Known gaps

- **Item names are a build step.** New items keep showing `#<id>` until
  `tools/trainer/resolve_items.mjs` is run against a `HOTBAR.DAT` that contains
  them. Values at `2,000,000` and above use an offset that is not understood,
  so they stay unnamed.
- **Icons need the network on a cold cache.** The proxy caches PNGs in
  `data/trainer/icon_cache`; a fresh deployment fetches each icon once.
- **The action index is only as current as the last plugin sheet dump.** Crafting
  actions above id 100,000 have no row in the Action sheet at all.
- **Anonymous history is browser-local.** Clearing site data clears it; only an
  account copy survives.
- **`HOTBAR.DAT` disagrees with the running client on one slot.** See the known
  gaps in `trainer-data-formats.md`.
- **Recognition mode is not built.** Cards are production only: name to press.
