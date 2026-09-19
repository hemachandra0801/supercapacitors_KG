import json
import os
import pandas as pd
from glob import glob
import re
from rapidfuzz import fuzz
import numpy as np
from sklearn.cluster import DBSCAN
import pickle

# Collect All Unique Raw Material Names

def gather_material_names(json_dir):
    raw_names = []
    for fpath in glob(os.path.join(json_dir, "*.json")):
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for mat in data.get("materials", []):
            name = mat.get("name", "").strip()
            if name:
                raw_names.append(name)
    return list(set(raw_names))  # unique names

raw_materials = gather_material_names("outputs_json")
print(f"Found {len(raw_materials)} unique material names.")


# Pre‑process Names

def clean_material_name(name):
    name = name.lower().strip()
    # Remove filler words (expand as needed)
    filler = r'\b(composite|electrode|as prepared|sample|film|coated|deposited|synthesized|fabricated|material)\b'
    name = re.sub(filler, '', name)
    # Remove extra spaces and punctuation (except / and -)
    name = re.sub(r'[^\w\s/-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

cleaned_names = [clean_material_name(n) for n in raw_materials]
# Create a mapping from cleaned -> original to preserve originals
name_map = dict(zip(cleaned_names, raw_materials))

print("Cleaned material names")

# Save name mapping locally

with open("name_map.pkl", "wb") as f:
    pickle.dump(name_map, f, protocol=pickle.HIGHEST_PROTOCOL)


# Load name mapping
with open("name_map.pkl", "rb") as f:
    name_map = pickle.load(f)


# Cluster Similar Names

def compute_distance_matrix(strings):
    n = len(strings)
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n):
            # Use token_sort_ratio to ignore word order
            sim = fuzz.token_sort_ratio(strings[i], strings[j])
            dist[i, j] = 100 - sim
            dist[j, i] = dist[i, j]
    return dist

cleaned_names = list(name_map.keys())

dist_matrix = compute_distance_matrix(cleaned_names)

clustering = DBSCAN(eps=15, min_samples=1, metric='precomputed').fit(dist_matrix)
labels = clustering.labels_

# Check clusters

from collections import defaultdict

clusters = defaultdict(list)
for label, name in zip(labels, cleaned_names):
    clusters[label].append(name)

for cid, names in clusters.items():
    if len(names) > 1:
        print(f"Cluster {cid}: {names[:10]}")


cluster_data = {
    "clusters": dict(clusters),
    "labels": labels,
    "cleaned_names": cleaned_names
}

import pickle

# Save clusters
with open("name_clusters.pkl", "wb") as f:
    pickle.dump(cluster_data, f)