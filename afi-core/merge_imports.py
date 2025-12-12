import json

FILES = ["import_data_dav.json", "import_data_cre.json"]
OUTPUT = "import_data.json"

merged = []

for fpath in FILES:
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                merged.extend(data)
            else:
                print(f"⚠️ {fpath} no es una lista.")
    except FileNotFoundError:
        print(f"⚠️ {fpath} no encontrado.")

with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)

print(f"✅ Merged {len(merged)} accounts into {OUTPUT}")
