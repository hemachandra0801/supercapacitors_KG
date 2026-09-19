import json
from pathlib import Path
from typing import Dict, Any, Set

# ============================================================
# CONFIG
# ============================================================

INPUT_DIR = Path("outputs_json")
OUTPUT_DIR = Path("outputs_json_final")

PROPERTIES_FILE = Path("properties_normalized.json")

BACKUP_ORIGINAL_PROPERTY_NAME = True

# ============================================================
# LOAD PROPERTY NORMALIZATION MAP
# ============================================================

def load_property_mapping(path: Path) -> Dict[str, str]:

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned_mapping = {}

    for k, v in data.items():

        if k is None:
            continue

        key = str(k).strip()

        if key == "":
            continue

        cleaned_mapping[key] = v

    return cleaned_mapping


# ============================================================
# PROPERTY NORMALIZER
# ============================================================

class PropertyNormalizer:

    def __init__(self, property_map: Dict[str, str]):

        self.property_map = property_map

        self.stats = {
            "normalized": 0,
            "missing_property_name_field": 0,
            "empty_property_name": 0,
            "unmatched_properties": set(),
            "errors": 0
        }

    def normalize_property(self, prop_obj: Dict[str, Any]):

        # Missing property_name field
        if "property_name" not in prop_obj:
            self.stats["missing_property_name_field"] += 1
            return

        property_name = prop_obj.get("property_name")

        # Empty/null property_name
        if property_name is None:

            self.stats["empty_property_name"] += 1
            return

        property_name = str(property_name).strip()

        if property_name == "":

            self.stats["empty_property_name"] += 1
            return

        # Preserve original property name
        if BACKUP_ORIGINAL_PROPERTY_NAME:
            prop_obj["original_property_name"] = property_name

        # Property not found in normalization map
        if property_name not in self.property_map:

            self.stats["unmatched_properties"].add(property_name)
            return

        normalized_name = self.property_map[property_name]

        # Safety check
        if normalized_name is None:
            return

        normalized_name = str(normalized_name).strip()

        if normalized_name == "":
            return

        # Apply normalization
        prop_obj["property_name"] = normalized_name

        self.stats["normalized"] += 1

    def traverse(self, data: Any):

        """
        Traverse recursively and normalize only inside
        performance_and_properties lists.
        """

        if isinstance(data, dict):

            # Process performance_and_properties
            if "performance_and_properties" in data:

                properties = data.get("performance_and_properties")

                if isinstance(properties, list):

                    for prop in properties:

                        if isinstance(prop, dict):
                            self.normalize_property(prop)

            # Continue recursion
            for value in data.values():
                self.traverse(value)

        elif isinstance(data, list):

            for item in data:
                self.traverse(item)


# ============================================================
# FILE PROCESSING
# ============================================================

def process_file(
    input_file: Path,
    output_file: Path,
    normalizer: PropertyNormalizer
):

    try:

        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        normalizer.traverse(data)

        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    except Exception as e:

        print(f"[ERROR] Failed processing {input_file}: {e}")

        normalizer.stats["errors"] += 1


# ============================================================
# MAIN
# ============================================================

def main():

    property_map = load_property_mapping(PROPERTIES_FILE)

    print(f"Loaded {len(property_map)} normalized properties")

    normalizer = PropertyNormalizer(property_map)

    OUTPUT_DIR.mkdir(exist_ok=True)

    json_files = list(INPUT_DIR.rglob("*.json"))

    print(f"Found {len(json_files)} JSON files\n")

    for idx, file_path in enumerate(json_files, 1):

        relative = file_path.relative_to(INPUT_DIR)
        output_file = OUTPUT_DIR / relative

        if idx % 1000 == 0:
            print(f"[{idx}/{len(json_files)}] Processing: {relative}")

        process_file(
            file_path,
            output_file,
            normalizer
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n================ SUMMARY ================")

    print(f"Normalized properties: {normalizer.stats['normalized']}")

    print(
        f"Missing property_name field: "
        f"{normalizer.stats['missing_property_name_field']}"
    )

    print(
        f"Empty/null property_name: "
        f"{normalizer.stats['empty_property_name']}"
    )

    print(f"Errors: {normalizer.stats['errors']}")

    unmatched = sorted(normalizer.stats["unmatched_properties"])

    print(f"\nUnmatched properties ({len(unmatched)}):")

    for p in unmatched:
        print(f"  - {p}")

    # ========================================================
    # SAVE UNMATCHED PROPERTIES
    # ========================================================

    unmatched_path = OUTPUT_DIR / "unmatched_properties.json"

    with open(unmatched_path, "w", encoding="utf-8") as f:
        json.dump(unmatched, f, indent=2, ensure_ascii=False)

    print(f"\nSaved unmatched properties to: {unmatched_path}")


if __name__ == "__main__":
    main()