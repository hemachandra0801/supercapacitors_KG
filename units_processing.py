import os
import json
import pickle
from glob import glob

# =========================================================
# CONFIG
# =========================================================

JSON_DIR = "outputs_json"

OUTPUT_UNITS_JSON = "unique_units.json"
OUTPUT_UNITS_PKL = "unique_units.pkl"

# =========================================================
# COLLECT UNITS
# =========================================================

all_units = []

json_files = glob(os.path.join(JSON_DIR, "*.json"))

print(f"Found {len(json_files)} JSON files")

for idx, fpath in enumerate(json_files):

    try:

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        materials = data.get("materials") or []

        for material in materials:

            properties = material.get(
                "performance_and_properties"
            ) or []

            for prop in properties:

                unit = prop.get("unit")

                if isinstance(unit, str):

                    unit = unit.strip()

                    if unit:
                        all_units.append(unit)

        # Progress logging
        if idx % 100 == 0:
            print(f"Processed {idx}/{len(json_files)} files")

    except Exception as e:

        print(f"\nFailed file: {fpath}")
        print(e)

# =========================================================
# UNIQUE UNITS
# =========================================================

unique_units = sorted(list(set(all_units)))

print("\n===================================")
print(f"Total unit entries: {len(all_units)}")
print(f"Unique units: {len(unique_units)}")
print("===================================\n")

# =========================================================
# PRINT SAMPLE
# =========================================================

print("Sample units:\n")

for unit in unique_units[:100]:
    print(unit)

# =========================================================
# SAVE JSON
# =========================================================

with open(OUTPUT_UNITS_JSON, "w", encoding="utf-8") as f:
    json.dump(
        unique_units,
        f,
        indent=2,
        ensure_ascii=False
    )

print(f"\nSaved unique units JSON:")
print(OUTPUT_UNITS_JSON)

# =========================================================
# SAVE PKL
# =========================================================

with open(OUTPUT_UNITS_PKL, "wb") as f:
    pickle.dump(
        unique_units,
        f,
        protocol=pickle.HIGHEST_PROTOCOL
    )

print(f"\nSaved unique units PKL:")
print(OUTPUT_UNITS_PKL)




# ============================================================================================== #




import json


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Path to your files
original_units_file = "unique_units.json"
normalized_units_file = "units_normalized.json"

# Load data
original_units = load_json(original_units_file)
normalized_data = load_json(normalized_units_file)

# Extract all normalized "original" fields
normalized_originals = {
    entry["original"]
    for entry in normalized_data.get("conversions", [])
    if "original" in entry
}

# Find missing units
missing_units = sorted([
    unit for unit in original_units
    if unit not in normalized_originals
])

# Print results
print(f"Total original units: {len(original_units)}")
print(f"Total normalized units: {len(normalized_originals)}")
print(f"Missing units: {len(missing_units)}")

print("\nUnits missing from normalized file:\n")
for unit in missing_units:
    print(unit)

# Optional: save missing units to a file
with open("units_missing.json", "w", encoding="utf-8") as f:
    json.dump(missing_units, f, indent=2, ensure_ascii=False)

print("\nMissing units saved to units_missing.json")




# ============================================================================================== #




import json
from pathlib import Path
from typing import Any, Set

# ============================================================
# CONFIG
# ============================================================

INPUT_DIR = Path("outputs_json")
UNITS_FILE = Path("units_normalized.json")

# ============================================================
# LOAD NORMALIZED UNITS
# ============================================================

with open(UNITS_FILE, "r", encoding="utf-8") as f:
    units_data = json.load(f)

normalized_units = {
    str(entry.get("original")).strip()
    for entry in units_data.get("conversions", [])
    if entry.get("original") is not None
}

# ============================================================
# COLLECT UNITS FROM PAPERS
# ============================================================

all_units: Set[str] = set()


def traverse(data: Any):

    if isinstance(data, dict):

        if "unit" in data:

            unit = data.get("unit")

            if unit is not None:

                unit = str(unit).strip()

                if unit != "":
                    all_units.add(unit)

        for value in data.values():
            traverse(value)

    elif isinstance(data, list):

        for item in data:
            traverse(item)


# ============================================================
# PROCESS ALL FILES
# ============================================================

json_files = list(INPUT_DIR.rglob("*.json"))

print(f"Scanning {len(json_files)} JSON files...\n")

for file_path in json_files:

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        traverse(data)

    except Exception as e:
        print(f"[ERROR] {file_path}: {e}")

# ============================================================
# FIND MISSING UNITS
# ============================================================

missing_units = sorted(all_units - normalized_units)

print("=" * 60)
print(f"Total unique units found     : {len(all_units)}")
print(f"Units already normalized     : {len(normalized_units)}")
print(f"Units still missing          : {len(missing_units)}")
print("=" * 60)

for unit in missing_units:
    print(unit)

# ============================================================
# SAVE MISSING UNITS
# ============================================================

output_file = "missing_units.json"

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(missing_units, f, indent=2, ensure_ascii=False)

print(f"\nSaved missing units to: {output_file}")




# ============================================================================================== #




import json
from pathlib import Path
from typing import Any, Set, List, Dict

# ============================================================
# CONFIG
# ============================================================

INPUT_DIR = Path("outputs_json")
UNITS_FILE = Path("units_normalized.json")

OUTPUT_FILE = Path("units_normalized_cleaned.json")

# ============================================================
# COLLECT ALL UNITS PRESENT IN PAPERS
# ============================================================

paper_units: Set[str] = set()


def traverse(data: Any):

    if isinstance(data, dict):

        if "unit" in data:

            unit = data.get("unit")

            if unit is not None:

                unit = str(unit).strip()

                if unit != "":
                    paper_units.add(unit)

        for value in data.values():
            traverse(value)

    elif isinstance(data, list):

        for item in data:
            traverse(item)


# ============================================================
# SCAN ALL JSON PAPERS
# ============================================================

json_files = list(INPUT_DIR.rglob("*.json"))

print(f"Scanning {len(json_files)} paper JSON files...\n")

for file_path in json_files:

    try:

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        traverse(data)

    except Exception as e:
        print(f"[ERROR] Failed reading {file_path}: {e}")

print(f"Found {len(paper_units)} unique units in papers.\n")

# ============================================================
# LOAD UNIT NORMALIZATION FILE
# ============================================================

with open(UNITS_FILE, "r", encoding="utf-8") as f:
    units_data = json.load(f)

conversions: List[Dict] = units_data.get("conversions", [])

print(f"Original conversion entries: {len(conversions)}")

# ============================================================
# REMOVE DUPLICATES + UNUSED ENTRIES
# ============================================================

seen_originals = set()

cleaned_conversions = []

removed_duplicates = []
removed_unused = []
invalid_entries = []

for entry in conversions:

    original = entry.get("original")

    # Invalid original
    if original is None:
        invalid_entries.append(entry)
        continue

    original = str(original).strip()

    # Empty original
    if original == "":
        invalid_entries.append(entry)
        continue

    # Duplicate detection
    if original in seen_originals:
        removed_duplicates.append(original)
        continue

    seen_originals.add(original)

    # Not present in papers
    if original not in paper_units:
        removed_unused.append(original)
        continue

    cleaned_conversions.append(entry)

# ============================================================
# SAVE CLEANED FILE
# ============================================================

cleaned_data = {
    "conversions": cleaned_conversions
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(cleaned_data, f, indent=2, ensure_ascii=False)

# ============================================================
# SUMMARY
# ============================================================

print("=" * 60)
print("CLEANING SUMMARY")
print("=" * 60)

print(f"Original entries                : {len(conversions)}")
print(f"Final cleaned entries           : {len(cleaned_conversions)}")
print(f"Removed duplicate entries       : {len(removed_duplicates)}")
print(f"Removed unused entries          : {len(removed_unused)}")
print(f"Removed invalid entries         : {len(invalid_entries)}")

# ============================================================
# OPTIONAL REPORTS
# ============================================================

Path("cleanup_reports").mkdir(exist_ok=True)

with open("cleanup_reports/removed_duplicates.json", "w", encoding="utf-8") as f:
    json.dump(sorted(set(removed_duplicates)), f, indent=2, ensure_ascii=False)

with open("cleanup_reports/removed_unused.json", "w", encoding="utf-8") as f:
    json.dump(sorted(set(removed_unused)), f, indent=2, ensure_ascii=False)

with open("cleanup_reports/invalid_entries.json", "w", encoding="utf-8") as f:
    json.dump(invalid_entries, f, indent=2, ensure_ascii=False)

print("\nReports saved in: cleanup_reports/")
print(f"Cleaned normalization file saved to: {OUTPUT_FILE}")