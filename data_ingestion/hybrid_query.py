from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import numpy as np

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "abcdefgh"))
model = SentenceTransformer('all-MiniLM-L6-v2')

def run_query(query, params=None):
    with driver.session() as session:
        result = session.run(query, params or {})
        return [record.data() for record in result]

hybrid_text = "nitrogen-doped carbon"
hybrid_embedding = model.encode(hybrid_text).tolist()

hybrid_query = """
CALL db.index.vector.queryNodes('material_embeddings', 20, $query_emb)
YIELD node AS m, score
MATCH (m)-[:EXHIBITS_PROPERTY]->(p:Property)
WHERE p.property_name = 'specific_capacitance' AND toFloat(p.value) > 200000
RETURN m.name AS material, toFloat(p.value) AS capacitance_F_per_kg, p.unit AS unit, score
ORDER BY score DESC
LIMIT 3
"""
print("\n=== Hybrid Query Results ===")
hybrid_results = run_query(hybrid_query, {"query_emb": hybrid_embedding})
for row in hybrid_results:
    print(f"{row['material']}: {row['capacitance_F_per_kg']} {row['unit']} (score {row['score']:.4f})")

driver.close()