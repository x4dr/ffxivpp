import sqlite3
from app.lodestone import fetch_character
from app.db import set_lodestone_link

# Mapping discord_id -> lodestone_id
mappings = {
    "229632496625516544": "59874367", # Vey
    "111117588553060352": "32267141", # Lookei
    "393428399353364503": "28630035", # Luneli
    "158302672414441481": "59662524", # Naghia
    "217068793543917569": "54185648", # Tehon
    "906214878367326251": "54185676", # saga
}

for d_id, l_id in mappings.items():
    print(f"Fetching {l_id}...")
    data = fetch_character(l_id)
    if "error" not in data:
        char_name = data.get("name")
        set_lodestone_link(d_id, l_id, char_name)
        print(f"Linked {d_id} to {l_id} ({char_name})")
    else:
        print(f"Failed to fetch {l_id}")
