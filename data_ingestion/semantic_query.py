from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import numpy as np

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "abcdefgh"))
model = SentenceTransformer('all-MiniLM-L6-v2')

query_text = """
A porous carbon material derived from biomass with high surface
area and good capacitance retention.
"""

query_embedding = model.encode(query_text).tolist()

# cypher = """
# CALL db.index.vector.queryNodes(
#     'material_embeddings',
#     $k,
#     $embedding
# )
# YIELD node, score

# RETURN
#     node.material_id AS material_id,
#     node.name AS material_name,
#     node.original_name AS original_name,
#     score
# ORDER BY score DESC
# """

cypher = """
CALL db.index.vector.queryNodes(
    'material_embeddings',
    $k,
    $embedding
)
YIELD node, score

OPTIONAL MATCH (node)-[:EXHIBITS_PROPERTY]->(cap:Property)
WHERE cap.property_name = 'specific_capacitance'

OPTIONAL MATCH (node)-[:EXHIBITS_PROPERTY]->(ssa:Property)
WHERE ssa.property_name = 'specific_surface_area'

RETURN
    node.material_id AS material_id,
    node.name AS material_name,
    node.original_name AS original_name,

    max(toString(cap.value)) AS specific_capacitance,
    max(cap.unit) AS capacitance_unit,

    max(toString(ssa.value)) AS surface_area,
    max(ssa.unit) AS surface_area_unit,

    score
ORDER BY score DESC
"""

with driver.session() as session:
    results = session.run(
        cypher,
        embedding=query_embedding,
        k=10
    )

    rows = list(results)

for row in rows:
    print(
        row["material_name"],
        row["surface_area"],
        row["score"]
    )