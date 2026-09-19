import pickle
import json
import unicodedata
import re
from collections import defaultdict

# =========================================================
# FILE PATHS
# =========================================================

INPUT_CLUSTERS = "properties_clustered.pkl"
INPUT_PROPERTIES = "properties.pkl"

OUTPUT_CLUSTERS = "properties_clustered_normalized.pkl"
OUTPUT_PROPERTIES = "properties_normalized.pkl"

# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(text):
    """
    Normalize unicode/scientific text inconsistencies.
    """

    if not isinstance(text, str):
        return text

    # Unicode normalization
    text = unicodedata.normalize("NFKC", text)

    # Normalize dash variants
    dash_map = {
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
    }

    for bad, good in dash_map.items():
        text = text.replace(bad, good)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()

# =========================================================
# NORMALIZE properties.pkl
# =========================================================

print("\nLoading properties.pkl...")

with open(INPUT_PROPERTIES, "rb") as f:
    properties = pickle.load(f)

print(f"Loaded {len(properties)} properties")

normalized_properties = []

for prop in properties:

    if isinstance(prop, str):
        normalized_properties.append(
            normalize_text(prop)
        )
    else:
        normalized_properties.append(prop)

# Remove duplicates while preserving order
normalized_properties = list(dict.fromkeys(normalized_properties))

print(f"Normalized property count: {len(normalized_properties)}")

# Save
with open(OUTPUT_PROPERTIES, "wb") as f:
    pickle.dump(normalized_properties, f)

print(f"Saved normalized properties to:")
print(OUTPUT_PROPERTIES)

# =========================================================
# NORMALIZE properties_clustered.pkl
# =========================================================

print("\nLoading properties_clustered.pkl...")

with open(INPUT_CLUSTERS, "rb") as f:
    clusters = pickle.load(f)

print(f"Loaded {len(clusters)} clusters")

normalized_clusters = {}

for cluster_id, cluster_data in clusters.items():

    # -----------------------------------------------------
    # CASE 1:
    # cluster_data is dict with "values"
    # -----------------------------------------------------

    if isinstance(cluster_data, dict):

        values = cluster_data.get("values", [])

        normalized_values = []

        for v in values:

            if isinstance(v, str):
                normalized_values.append(
                    normalize_text(v)
                )

        # Remove duplicates
        normalized_values = list(dict.fromkeys(normalized_values))

        new_cluster = cluster_data.copy()
        new_cluster["values"] = normalized_values

        normalized_clusters[cluster_id] = new_cluster

    # -----------------------------------------------------
    # CASE 2:
    # cluster_data is directly a list
    # -----------------------------------------------------

    elif isinstance(cluster_data, list):

        normalized_values = []

        for v in cluster_data:

            if isinstance(v, str):
                normalized_values.append(
                    normalize_text(v)
                )

        # Remove duplicates
        normalized_values = list(dict.fromkeys(normalized_values))

        normalized_clusters[cluster_id] = normalized_values

    # -----------------------------------------------------
    # Unknown format
    # -----------------------------------------------------

    else:

        normalized_clusters[cluster_id] = cluster_data

# Save
with open(OUTPUT_CLUSTERS, "wb") as f:
    pickle.dump(normalized_clusters, f)

print(f"\nSaved normalized clusters to:")
print(OUTPUT_CLUSTERS)

print("\nDone.")





# ===============================================================================================================





import os
import json
import unicodedata
import re
from glob import glob
from copy import deepcopy

# =========================================================
# CONFIG
# =========================================================

INPUT_DIR = "outputs_json"
OUTPUT_DIR = "outputs_json_normalized"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(text):
    """
    Normalize unicode/scientific text inconsistencies.
    """

    if not isinstance(text, str):
        return text

    # Unicode normalization
    text = unicodedata.normalize("NFKC", text)

    # Normalize dash variants
    dash_map = {
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
    }

    for bad, good in dash_map.items():
        text = text.replace(bad, good)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()

# =========================================================
# RECURSIVE NORMALIZATION
# =========================================================

def normalize_json(obj):
    """
    Recursively normalize ALL strings in nested JSON.
    """

    # ---------------------------------------------
    # String
    # ---------------------------------------------
    if isinstance(obj, str):
        return normalize_text(obj)

    # ---------------------------------------------
    # List
    # ---------------------------------------------
    elif isinstance(obj, list):
        return [normalize_json(item) for item in obj]

    # ---------------------------------------------
    # Dict
    # ---------------------------------------------
    elif isinstance(obj, dict):

        normalized_dict = {}

        for key, value in obj.items():

            # Normalize keys
            normalized_key = normalize_text(key)

            normalized_dict[normalized_key] = normalize_json(value)

        return normalized_dict

    # ---------------------------------------------
    # Other types
    # ---------------------------------------------
    else:
        return obj

# =========================================================
# PROCESS FILES
# =========================================================

json_files = glob(os.path.join(INPUT_DIR, "*.json"))

print(f"Found {len(json_files)} JSON files")

success = 0
failed = 0

for idx, fpath in enumerate(json_files):

    try:

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Normalize recursively
        normalized_data = normalize_json(data)

        # Save
        output_path = os.path.join(
            OUTPUT_DIR,
            os.path.basename(fpath)
        )

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                normalized_data,
                f,
                indent=2,
                ensure_ascii=False
            )

        success += 1

        if idx % 100 == 0:
            print(f"Processed {idx}/{len(json_files)} files")

    except Exception as e:

        failed += 1

        print(f"\nFailed: {fpath}")
        print(e)

# =========================================================
# SUMMARY
# =========================================================

print("\n===================================")
print(f"Completed")
print(f"Successful: {success}")
print(f"Failed: {failed}")
print(f"Saved normalized files to:")
print(OUTPUT_DIR)
print("===================================")