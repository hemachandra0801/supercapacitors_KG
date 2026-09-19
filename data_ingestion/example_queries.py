from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import numpy as np
from datetime import datetime

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "abcdefgh"))
model = SentenceTransformer('all-MiniLM-L6-v2')  # 384-dimensional embeddings

# # Example 1
# def semantic_search(query_text, top_k=10):
#     query_emb = model.encode(query_text).tolist()
#     with driver.session() as session:
#         result = session.run("""
#             CALL db.index.vector.queryNodes('material_embeddings', $top_k, $query_emb)
#             YIELD node, score
#             WHERE NOT node:Electrolyte   // optional filter
#             RETURN node.name AS name, node.material_id AS id, score
#             ORDER BY score DESC
#         """, top_k=top_k, query_emb=query_emb)
#         return [dict(record) for record in result]
    

# results = semantic_search("porous carbon with high capacitance and cycling stability")
# for r in results:
#     print(r['name'], r['score'])


# #Example 2
def semantic_search(query_text, top_k=10):
    query_emb = model.encode(query_text).tolist()
    with driver.session() as session:
        result = session.run("""
            CALL db.index.vector.queryNodes('material_embeddings', 20, $query_emb)
            YIELD node AS m, score
            MATCH (m)-[:EXHIBITS_PROPERTY]->(p:Property {property_name: 'specific_capacitance'})
            WHERE p.value > 300000
            RETURN m.name, p.value, p.unit, score
            ORDER BY score DESC
            LIMIT 10
        """, top_k=top_k, query_emb=query_emb)
        return [dict(record) for record in result]
    
start = datetime.now()
results = semantic_search("Nitrogen‑doped carbon materials that also have specific capacitance > 300,000 F/kg")
for r in results:
    print(r['m.name'], r['p.value'], r['p.unit'], r['score'])
end = datetime.now()

print("Time taken: ", end - start)


# # Example 3 0 purely semantic

# import time

# query_text = """
# A porous carbon material derived from biomass with high surface
# area and good capacitance retention.
# """

# start = time.time()

# query_embedding = model.encode(query_text).tolist()

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

# with driver.session() as session:
#     results = session.run(
#         cypher,
#         embedding=query_embedding,
#         k=10
#     )

#     rows = list(results)

# elapsed = time.time() - start

# print(f"Semantic search time: {elapsed:.3f} sec\n")

# for row in rows:
#     print(
#         row["material_name"],
#         row["score"]
#     )