import json
import math
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple
import re

# ============================================================
# CONFIG
# ============================================================

INPUT_DIR = Path("outputs_json")
OUTPUT_DIR = Path("outputs_json_normalized")
UNITS_FILE = Path("units_normalized.json")

BACKUP_ORIGINAL_UNIT = True
BACKUP_ORIGINAL_VALUE = True

# ============================================================
# LOAD UNIT CONVERSIONS
# ============================================================

def load_unit_conversions(units_file: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load unit conversion mappings.

    Returns:
        {
            "mAh g-1": {
                "si_unit": "A s kg-1",
                "factor": 3600.0,
                ...
            }
        }
    """

    with open(units_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversions = {}

    for entry in data.get("conversions", []):

        original = entry.get("original")

        if original is None:
            continue

        conversions[str(original).strip()] = entry

    return conversions


# ============================================================
# NUMERIC CHECKING
# ============================================================

def safe_float(value: Any) -> Tuple[bool, float]:
    """
    Safely attempt numeric conversion.
    """

    if value is None:
        return False, None

    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return False, None
        return True, float(value)

    if isinstance(value, str):
        value = value.strip()

        if value == "":
            return False, None

        try:
            return True, float(value)
        except Exception:
            return False, None

    return False, None


# ============================================================
# FACTOR PARSING
# ============================================================

def parse_factor_operation(factor):
    """
    Handles:
        1000
        "1000"
        "add 273.15"

    Returns:
        ("multiply", 1000)
        ("add", 273.15)
    """

    if factor is None:
        return None, None

    # Numeric factor
    if isinstance(factor, (int, float)):
        return "multiply", float(factor)

    factor_str = str(factor).strip()

    # add operation
    add_match = re.match(
        r"^add\s+([-+]?\d*\.?\d+)$",
        factor_str,
        re.IGNORECASE
    )

    if add_match:
        return "add", float(add_match.group(1))

    # multiplication factor
    try:
        return "multiply", float(factor_str)
    except Exception:
        return None, None
    

# ============================================================
# SI UNIT CLEANING
# ============================================================

def resolve_si_unit(si_unit, original_unit):
    """
    Handles special SI unit cases.

    Rules:
    - dimensionless -> "1"
    - null -> original unit
    - unable to convert -> original unit
    """

    if si_unit is None:
        return original_unit

    si_unit = str(si_unit).strip()

    if si_unit == "":
        return original_unit

    if si_unit.lower() == "unable to convert":
        return original_unit

    if si_unit.lower() == "dimensionless":
        return "1"

    return si_unit


# ============================================================
# NORMALIZATION CORE
# ============================================================

class UnitNormalizer:

    def __init__(self, conversion_map: Dict[str, Dict[str, Any]]):

        self.conversion_map = conversion_map

        self.stats = {
            "normalized": 0,
            "add_operations": 0,
            "multiply_operations": 0,
            "skipped_missing_unit": 0,
            "skipped_missing_factor": 0,
            "skipped_non_numeric_value": 0,
            "unmatched_units": set(),
            "errors": 0
        }

    def normalize_value_and_unit(self, obj: Dict[str, Any]):

        if "unit" not in obj:
            return

        original_unit = obj.get("unit")

        # Skip empty units
        if original_unit is None or str(original_unit).strip() == "":
            self.stats["skipped_missing_unit"] += 1
            return

        original_unit = str(original_unit).strip()

        # Preserve original metadata ALWAYS
        if BACKUP_ORIGINAL_UNIT:
            obj["original_unit"] = original_unit

        if BACKUP_ORIGINAL_VALUE and "value" in obj:
            obj["original_value"] = obj.get("value")

        # No conversion available
        if original_unit not in self.conversion_map:
            self.stats["unmatched_units"].add(original_unit)
            return

        conversion = self.conversion_map[original_unit]

        factor = conversion.get("factor")
        si_unit = conversion.get("si_unit")

        # Resolve SI unit special cases
        final_unit = resolve_si_unit(
            si_unit,
            original_unit
        )

        # Always update unit if conversion exists
        obj["unit"] = final_unit

        # Missing factor
        if factor is None:
            self.stats["skipped_missing_factor"] += 1
            return

        operation, factor_value = parse_factor_operation(factor)

        if operation is None:
            self.stats["skipped_missing_factor"] += 1
            return

        value = obj.get("value")

        is_numeric, numeric_value = safe_float(value)

        # Cannot scale non-numeric values
        if not is_numeric:
            self.stats["skipped_non_numeric_value"] += 1
            return

        # ====================================================
        # APPLY CONVERSION
        # ====================================================

        try:

            if operation == "multiply":

                normalized_value = numeric_value * factor_value
                self.stats["multiply_operations"] += 1

            elif operation == "add":

                normalized_value = numeric_value + factor_value
                self.stats["add_operations"] += 1

            else:
                self.stats["errors"] += 1
                return

            obj["value"] = normalized_value

            self.stats["normalized"] += 1

        except Exception:
            self.stats["errors"] += 1

    def traverse(self, data: Any):

        if isinstance(data, dict):

            # Normalize current object if applicable
            if "value" in data and "unit" in data:
                self.normalize_value_and_unit(data)

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
    normalizer: UnitNormalizer
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

    conversion_map = load_unit_conversions(UNITS_FILE)

    normalizer = UnitNormalizer(conversion_map)

    OUTPUT_DIR.mkdir(exist_ok=True)

    json_files = list(INPUT_DIR.rglob("*.json"))

    print(f"Found {len(json_files)} JSON files")

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

    print(f"Normalized entries: {normalizer.stats['normalized']}")
    print(f"Multiply operations: {normalizer.stats['multiply_operations']}")
    print(f"Add operations: {normalizer.stats['add_operations']}")

    print(f"Missing unit skipped: {normalizer.stats['skipped_missing_unit']}")
    print(f"Missing factor skipped: {normalizer.stats['skipped_missing_factor']}")
    print(f"Non-numeric value skipped: {normalizer.stats['skipped_non_numeric_value']}")
    print(f"Errors: {normalizer.stats['errors']}")

    unmatched = sorted(normalizer.stats["unmatched_units"])

    print(f"\nUnmatched units ({len(unmatched)}):")

    for u in unmatched:
        print(f"  - {u}")

    # Save unmatched units
    unmatched_path = OUTPUT_DIR / "unmatched_units.json"

    with open(unmatched_path, "w", encoding="utf-8") as f:
        json.dump(unmatched, f, indent=2, ensure_ascii=False)

    print(f"\nSaved unmatched units to: {unmatched_path}")


if __name__ == "__main__":
    main()