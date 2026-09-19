import json
import os
import re
import unicodedata
from pathlib import Path
from collections import Counter
import numpy as np
import pandas as pd
import networkx as nx
import faiss
import torch
from sentence_transformers import SentenceTransformer
from rapidfuzz import fuzz
from tqdm import tqdm

# ----------------------------------------------------------------------
# 0. CONFIGURATION
# ----------------------------------------------------------------------
JSON_DIR = "outputs_json"
OUTPUT_MAPPING = "material_name_mapping.csv"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH_SIZE = 256

# Graph thresholds
COSINE_THRESHOLD = 0.95
FUZZY_STRING_THRESHOLD = 90
FAISS_K_NEIGHBORS = 50

# ----------------------------------------------------------------------
# 1. READING & EXTRACTING
# ----------------------------------------------------------------------
def load_all_materials(json_dir):
    """
    Walk through all JSON files, extract material names and metadata.
    Returns a list of dicts with doi, material_index, raw_name,
    formula, role.
    """
    records = []
    json_files = list(Path(json_dir).rglob("*.json"))
    print(f"Found {len(json_files)} JSON files")

    for filepath in tqdm(json_files, desc="Loading JSONs"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                paper = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        doi = paper.get("metadata", {}).get("doi", str(filepath.stem))
        materials = paper.get("materials", [])
        for idx, mat in enumerate(materials):
            name = mat.get("name")
            if name and isinstance(name, str):
                records.append({
                    "doi": doi,
                    "material_index": idx,
                    "raw_name": name.strip(),
                    "formula": mat.get("formula"),
                    "role": mat.get("role")
                })
    print(f"Total raw material entries: {len(records)}")
    return records

# ----------------------------------------------------------------------
# 2. PREPROCESSING
# ----------------------------------------------------------------------
def clean_name(raw):
    """Normalise string but do not strip morphology terms."""
    name = unicodedata.normalize("NFKC", raw)
    name = name.lower()
    # Remove common decorative symbols but keep hyphens, slashes, etc.
    name = re.sub(r"[*•★♣♦♥♠★†‡]", " ", name)
    # Replace multiple whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name

def preprocess_records(records):
    """Add 'cleaned_name' field to each record."""
    for rec in records:
        rec["cleaned_name"] = clean_name(rec["raw_name"])
    return records

# ----------------------------------------------------------------------
# 3. EMBEDDING GENERATION
# ----------------------------------------------------------------------
def generate_embeddings(texts, model_name=EMBEDDING_MODEL, device=DEVICE, batch_size=BATCH_SIZE):
    model = SentenceTransformer(model_name, device=device)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True  # cosine similarity via inner product
    )
    return embeddings

# ----------------------------------------------------------------------
# 4. FAST SIMILARITY GRAPH
# ----------------------------------------------------------------------
def build_similarity_graph(embeddings, cosine_thresh=COSINE_THRESHOLD, k_neighbors=FAISS_K_NEIGHBORS):
    dim = embeddings.shape[1]
    N = embeddings.shape[0]

    nlist = int(4 * np.sqrt(N)) if N > 1000 else 1
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    if nlist > 1:
        index.train(embeddings)
    index.add(embeddings)
    index.nprobe = 10

    similarities, indices = index.search(embeddings, k_neighbors)

    G = nx.Graph()
    G.add_nodes_from(range(N))

    for i in range(N):
        for j_idx, sim in zip(indices[i], similarities[i]):
            j = int(j_idx)
            if i == j:
                continue
            if sim >= cosine_thresh:
                G.add_edge(i, j)
    return G

def add_string_filter(G, records, threshold=FUZZY_STRING_THRESHOLD):
    """Remove edges between nodes whose cleaned names have low fuzzy token_sort_ratio."""
    edges_to_remove = []
    for u, v in G.edges():
        name_u = records[u]["cleaned_name"]
        name_v = records[v]["cleaned_name"]
        score = fuzz.token_sort_ratio(name_u, name_v)
        if score < threshold:
            edges_to_remove.append((u, v))
    G.remove_edges_from(edges_to_remove)
    return G

# ----------------------------------------------------------------------
# 5. HARD RULE‑BASED EDGE FILTERS
# ----------------------------------------------------------------------
def get_concentration_value(name):
    """
    Extract numerical molarity/concentration from a name.
    Returns a float or None.
    Handles: "6 M", "0.1 M", "1 mol/L", "6.0 m", etc.
    """
    match = re.search(r'(\d+\.?\d*)\s*(?:M|mol/L)', name, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

def remove_concentration_edges(G, records):
    """Split edges when both sides have a concentration and values differ."""
    to_remove = []
    for u, v in G.edges():
        c_u = get_concentration_value(records[u]["cleaned_name"])
        c_v = get_concentration_value(records[v]["cleaned_name"])
        if c_u is not None and c_v is not None and c_u != c_v:
            to_remove.append((u, v))
    G.remove_edges_from(to_remove)
    return G

def normalize_formula(formula):
    """Simple formula normalizer: lowercase, remove spaces."""
    if not formula or not isinstance(formula, str):
        return None
    return re.sub(r'\s+', '', formula.lower())

def remove_formula_mismatch_edges(G, records):
    """If both nodes have a formula and they differ, split."""
    to_remove = []
    for u, v in G.edges():
        f_u = normalize_formula(records[u].get("formula"))
        f_v = normalize_formula(records[v].get("formula"))
        if f_u and f_v and f_u != f_v:
            to_remove.append((u, v))
    G.remove_edges_from(to_remove)
    return G

def remove_role_mismatch_edges(G, records):
    """If both nodes have a role and they differ, split (e.g., electrolyte vs active_material)."""
    to_remove = []
    for u, v in G.edges():
        r_u = records[u].get("role")
        r_v = records[v].get("role")
        if r_u and r_v and r_u != r_v:
            to_remove.append((u, v))
    G.remove_edges_from(to_remove)
    return G

def product_code_tokens(name):
    """Return set of alphanumeric tokens that look like product codes (length ≥ 4)."""
    return set(re.findall(r'\b[A-Z0-9]{4,}\b', name))

def remove_product_code_mismatch_edges(G, records):
    """If both nodes have product codes and they differ, split."""
    to_remove = []
    for u, v in G.edges():
        codes_u = product_code_tokens(records[u]["cleaned_name"])
        codes_v = product_code_tokens(records[v]["cleaned_name"])
        if codes_u and codes_v and codes_u != codes_v:
            to_remove.append((u, v))
    G.remove_edges_from(to_remove)
    return G

def get_dopants(name):
    """
    Extract dopant elements from patterns like 'La-doped', 'N-doped',
    'La,Sr-codoped'. Returns a frozenset of element symbols in lowercase.
    """
    matches = re.findall(r'([A-Za-z]+)-(?:co)?doped', name)
    if matches:
        dopants = set()
        for m in matches:
            for elem in re.split(r'[,/]', m):
                elem = elem.strip()
                if elem:
                    dopants.add(elem.lower())
        return frozenset(dopants) if dopants else None
    return None

def remove_dopant_mismatch_edges(G, records):
    """If both nodes have dopants and they differ, split."""
    to_remove = []
    for u, v in G.edges():
        d_u = get_dopants(records[u]["cleaned_name"])
        d_v = get_dopants(records[v]["cleaned_name"])
        if d_u is not None and d_v is not None and d_u != d_v:
            to_remove.append((u, v))
    G.remove_edges_from(to_remove)
    return G

# ----------------------------------------------------------------------
# 6. CANONICAL NAME SELECTION
# ----------------------------------------------------------------------
def clean_canonical(name):
    """
    Remove obvious role / synthesis prefixes so the canonical name
    is just the material, e.g.
    "binder - polyvinylidene difluoride (pvdf)" -> "polyvinylidene difluoride (pvdf)"
    "conductive additive: acetylene black (ab)" -> "acetylene black (ab)"
    """
    # Remove leading role tags (case insensitive)
    name = re.sub(
        r'^(binder\s*[-:]\s*|conductive\s*additive\s*[-:]\s*|electrolyte\s*[-:]\s*)',
        '',
        name,
        flags=re.IGNORECASE
    )
    return name.strip()

def rule_based_canonical(names_with_freq):
    """
    Pick the best canonical name from a list of (name, frequency) tuples.
    Favours shorter, more generic names that still look like a chemical.
    """
    # Score: primary = length of split tokens (shorter is better)
    # secondary = total length (shorter is better)
    candidates = sorted(names_with_freq, key=lambda x: (len(x[0].split()), -x[1], len(x[0])))
    # Prefer names that contain at least one element symbol
    for name, _ in candidates:
        if re.search(r'\b[A-Z][a-z]?\b', name):   # e.g., "Fe", "N", "Cu"
            return clean_canonical(name)
    return clean_canonical(candidates[0][0])

def assign_canonical_names(unique_records, clusters):
    """
    Given connected components (lists of node indices) and
    unique_records list, return dict {node_index: canonical_name}.
    """
    node_to_canon = {}
    for cluster in tqdm(clusters, desc="Canonicalising clusters"):
        if len(cluster) == 1:
            idx = cluster[0]
            node_to_canon[idx] = clean_canonical(unique_records[idx]["cleaned_name"])
            continue

        # Collect names and their frequencies within the cluster
        cluster_names = [unique_records[i]["cleaned_name"] for i in cluster]
        name_counts = Counter(cluster_names)
        name_freq = [(name, name_counts[name]) for name in set(cluster_names)]

        canonical = rule_based_canonical(name_freq)
        for idx in cluster:
            node_to_canon[idx] = canonical
    return node_to_canon

# ----------------------------------------------------------------------
# 7. MAIN PIPELINE
# ----------------------------------------------------------------------
def main():
    # 1. Load records from JSONs
    records = load_all_materials(JSON_DIR)

    # 2. Preprocess names (normalisation only)
    records = preprocess_records(records)

    # 3. Build a unique set of cleaned names for embedding
    cleaned_names = [rec["cleaned_name"] for rec in records]
    unique_names, inverse_indices = np.unique(cleaned_names, return_inverse=True)
    print(f"Unique cleaned names: {len(unique_names)}")

    # Create a list of representative records for unique indices
    unique_records = []
    seen = {}
    for rec in records:
        name = rec["cleaned_name"]
        if name not in seen:
            seen[name] = len(unique_records)
            unique_records.append({
                "cleaned_name": name,
                "formula": rec.get("formula"),
                "role": rec.get("role")
            })

    unique_index_from_name = {name: idx for idx, name in enumerate(unique_names)}
    unique_records = [None] * len(unique_names)
    for rec in records:
        idx = unique_index_from_name[rec["cleaned_name"]]
        if unique_records[idx] is None:
            unique_records[idx] = {
                "cleaned_name": rec["cleaned_name"],
                "formula": rec.get("formula"),
                "role": rec.get("role")
            }

    # 4. Generate embeddings for unique names
    embeddings = generate_embeddings(unique_names)

    # 5. Build initial similarity graph
    G = build_similarity_graph(embeddings)
    print(f"Graph after cosine filter: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # 6. Apply fuzzy string filter
    G = add_string_filter(G, unique_records)
    print(f"Graph after fuzzy filter: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # 7. Apply hard chemical filters
    G = remove_concentration_edges(G, unique_records)
    G = remove_formula_mismatch_edges(G, unique_records)
    G = remove_role_mismatch_edges(G, unique_records)
    G = remove_product_code_mismatch_edges(G, unique_records)
    G = remove_dopant_mismatch_edges(G, unique_records)
    print(f"Graph after all hard filters: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # 8. Extract clusters (connected components)
    clusters = [list(comp) for comp in nx.connected_components(G)]
    print(f"Number of clusters: {len(clusters)}")

    # 9. Assign canonical names to each unique node
    node_to_canon_unique = assign_canonical_names(unique_records, clusters)

    # 10. Map canonical names back to every original record
    canonical_per_record = []
    for orig_idx, unique_idx in enumerate(inverse_indices):
        canonical_per_record.append(node_to_canon_unique[unique_idx])

    # 11. Create the final mapping DataFrame
    df = pd.DataFrame(records)
    df["canonical_name"] = canonical_per_record
    df_out = df[["doi", "material_index", "raw_name", "cleaned_name", "canonical_name"]]
    df_out.to_csv(OUTPUT_MAPPING, index=False)
    print(f"Mapping saved to {OUTPUT_MAPPING}")

if __name__ == "__main__":
    main()