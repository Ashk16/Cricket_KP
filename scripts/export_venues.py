import json
from pathlib import Path

v = json.load(open(Path(__file__).parent.parent / "data/_venues_api.json"))
out = Path(__file__).parent.parent / "data/_all_venues.tsv"
out.write_text("\n".join(f"{x['id']}\t{x['name']}\t{x.get('city', '')}" for x in v), encoding="utf-8")
print(len(v), "written to", out)
