import pandas as pd
from neo4j import GraphDatabase
from tqdm import tqdm

# ---------------------------
# CONFIGURATION
# ---------------------------

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = ""

CSV_PATH = "supercapacitors_final.csv"

BATCH_SIZE = 2000

# ---------------------------
# LOAD CSV
# ---------------------------

print("Loading CSV...")

df = pd.read_csv(CSV_PATH)

# Keep only rows with DOI and cover_date
df = df[["doi", "cover_date"]].dropna()

# Normalize DOIs
df["doi"] = (
    df["doi"]
    .astype(str)
    .str.strip()
    .str.lower()
)

doi_to_cover_date = dict(
    zip(df["doi"], df["cover_date"])
)

print(f"Loaded {len(doi_to_cover_date):,} DOI → cover_date mappings")

# ---------------------------
# CONNECT TO NEO4J
# ---------------------------

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD)
)

# ---------------------------
# FETCH ALL PAPERS
# ---------------------------

FETCH_QUERY = """
MATCH (p:PaperSource)
WHERE p.doi IS NOT NULL
RETURN elementId(p) AS id,
       toLower(trim(p.doi)) AS doi
"""

with driver.session() as session:
    records = session.run(FETCH_QUERY)
    papers = list(records)

print(f"Found {len(papers):,} PaperSource nodes")

# ---------------------------
# PREPARE UPDATES
# ---------------------------

updates = []

missing = 0

for row in papers:
    doi = row["doi"]

    cover_date = doi_to_cover_date.get(doi)

    if cover_date is not None:
        updates.append({
            "id": row["id"],
            "cover_date": str(cover_date)
        })
    else:
        missing += 1

print(f"Matched papers: {len(updates):,}")
print(f"Missing DOIs : {missing:,}")

# ---------------------------
# UPDATE IN BATCHES
# ---------------------------

UPDATE_QUERY = """
UNWIND $rows AS row

MATCH (p:PaperSource)
WHERE elementId(p) = row.id

SET p.cover_date = row.cover_date
"""

with driver.session() as session:

    for i in tqdm(range(0, len(updates), BATCH_SIZE)):

        batch = updates[i:i + BATCH_SIZE]

        session.run(
            UPDATE_QUERY,
            rows=batch
        )

print("Done.")

driver.close()