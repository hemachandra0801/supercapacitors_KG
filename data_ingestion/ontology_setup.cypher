// PaperSource
CREATE CONSTRAINT paper_doi IF NOT EXISTS FOR (p:PaperSource) REQUIRE p.doi IS UNIQUE;

// Material
CREATE CONSTRAINT material_id IF NOT EXISTS FOR (m:Material) REQUIRE m.material_id IS UNIQUE;

// Property – will use a composite ID (material+property_name+condition_hash) but we can index property_name
CREATE INDEX property_name_idx IF NOT EXISTS FOR (p:Property) ON (p.property_name);
CREATE INDEX property_value_idx IF NOT EXISTS FOR (p:Property) ON (p.value);

// TestCondition – no uniqueness, but index condition_name
CREATE INDEX condition_name_idx IF NOT EXISTS FOR (tc:TestCondition) ON (tc.condition_name);

CREATE INDEX morphology_desc IF NOT EXISTS FOR (m:Morphology) ON (m.description);
CREATE INDEX precursor_name IF NOT EXISTS FOR (pc:Precursor) ON (pc.name);
CREATE INDEX material_name IF NOT EXISTS FOR (m:Material) ON (m.name);