from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import numpy as np

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "abcdefgh"))
model = SentenceTransformer('all-MiniLM-L6-v2')  # 384-dimensional embeddings

def build_material_text(tx):
    query = """
    MATCH (m:Material)
    WHERE NOT m:Electrolyte   // optional: skip electrolytes if you only want electrode materials
    OPTIONAL MATCH (m)-[:HAS_MORPHOLOGY]->(morph:Morphology)
    OPTIONAL MATCH (m)-[:PRODUCED_BY]->(s:SynthesisStep)-[:USES_METHOD]->(sm:SynthesisMethod)
    OPTIONAL MATCH (s)-[:USES_PRECURSOR]->(pc:Precursor)
    OPTIONAL MATCH (m)-[:EXHIBITS_PROPERTY]->(p:Property)
    WHERE p.property_name IN ['specific_capacitance', 'energy_density', 'specific_surface_area', 'capacitance_retention']
    WITH m, morph, sm, pc, p
    ORDER BY p.value DESC
    RETURN m.material_id AS id,
           m.name AS name,
           m.original_name AS original_name,
           m.role AS role,
           morph.description AS morphology,
           collect(DISTINCT sm.name) AS methods,
           collect(DISTINCT pc.original_name) AS precursors,
           collect(DISTINCT {name: p.property_name, value: p.original_value, unit: p.original_unit})[..5] AS properties
    """
    result = tx.run(query)
    texts = {}
    for record in result:
        parts = [f"Material: {record['name']}",
                 f"Original name: {record['original_name']}",
                 f"Role: {record['role']}"]
        if record['morphology']:
            parts.append(f"Morphology: {record['morphology']}")
        if record['methods']:
            parts.append(f"Synthesis methods: {', '.join(record['methods'])}")
        if record['precursors']:
            parts.append(f"Precursors: {', '.join(record['precursors'])}")
        if record['properties']:
            props = [f"{p['name']}: {p['value']} {p['unit']}" for p in record['properties']]
            parts.append(f"Key properties: {', '.join(props)}")
        texts[record['id']] = " ".join(parts)
    return texts

# Extract texts from Neo4j
with driver.session() as session:
    material_texts = session.execute_read(build_material_text)

# Compute embeddings
embeddings = {}
for mat_id, text in material_texts.items():
    emb = model.encode(text).tolist()
    embeddings[mat_id] = emb


def set_embedding(tx, mat_id, embedding):
    tx.run(
        "MATCH (m:Material {material_id: $id}) SET m.embedding = $emb",
        id=mat_id, emb=embedding
    )

with driver.session() as session:
    for mat_id, emb in embeddings.items():
        session.execute_write(set_embedding, mat_id, emb)