from neo4j import GraphDatabase
import json, uuid, re, glob

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "abcdefgh"))

def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"

def parse_electrolyte(elec_str):
    # Simple extraction of concentration and solute from "6 M KOH"
    match = re.match(r'(\d+\.?\d*)\s*(M|mM|µM|uM|mol/L)?\s*(\w+)?', elec_str)
    if match:
        conc = float(match.group(1))
        unit = match.group(2) or "M"
        solute = match.group(3) or ""
        return conc, unit, solute
    return None, "", elec_str

def parse_electrolyte_complex(text):
    """
    Parse electrolyte description into components.
    Returns:
        original (str): full text
        components (list of dicts): each dict has solute, concentration (float), unit
        solvent (str): solvent if mentioned, else ''
    """
    if not text:
        return "", "", ""
    
    original = text.strip()
    # Remove leading/trailing descriptors like "aqueous solution", "electrolyte", "gel"
    # but keep them for the solvent field
    text = re.sub(r'\b(aqueous|solution|electrolyte|gel)\b', '', original, flags=re.I).strip()
    
    # Separate solvent if ' in ' or ' in ' or '/' before non-salt parts
    solvent = ''
    # Look for pattern "in <solvent>" at the end or after a comma
    solvent_match = re.search(r'\bin\s+([\w\s,]+)$', text, re.I)
    if solvent_match:
        solvent = solvent_match.group(1).strip()
        text = text[:solvent_match.start()].strip()
    # Also handle cases like "PC", "AN", "acetonitrile" after a slash
    # but keep it simple: if no "in", check for known solvent names? We'll leave that for later.
    
    # Split multiple salts on '+' or 'and'
    # But avoid splitting compounds like "K3C6H5O7" which has no plus.
    parts = re.split(r'\s+\+\s+|\s+and\s+', text)
    components = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Try to parse "0.5 M LiClO4" or "1 M H2SO4" or "6 M KOH"
        match = re.match(r'(\d+\.?\d*)\s*(M|mM|µM|uM|mol/L)?\s*(\w[\w\s]*)', part)
        if match:
            conc = float(match.group(1))
            unit = match.group(2) or "M"
            solute = match.group(3).strip()
            components.append({'solute': solute, 'concentration': conc, 'unit': unit})
        else:
            # No concentration: store as raw solute (e.g., "K3C6H5O7/glycol/acetonitrile")
            components.append({'solute': part, 'concentration': None, 'unit': None})
    
    return original, components, solvent

def extract_numeric_and_unit(val_str):
    # Try to split "1 A/g" into (1.0, "A/g")
    if isinstance(val_str, (int, float)):
        return val_str, ""
    match = re.match(r'([+-]?\d+\.?\d*)\s*(.*)', str(val_str))
    if match:
        return float(match.group(1)), match.group(2)
    return None, ""

def ingest_multiple_papers(tx, papers):
    for data in papers:
        ingest_paper(tx, data)

def ingest_paper(tx, paper_data):
    doi = paper_data["metadata"]["doi"]
    title = paper_data["metadata"]["title"]
    # Create PaperSource (no year, only doi and title)
    tx.run("MERGE (p:PaperSource {doi: $doi}) SET p.title = $title", doi=doi, title=title)

    for mat in (paper_data.get("materials", []) or []):
        # ----- Material node -----
        mat_id = uid("mat")
        canonical = mat["name"]               # already standardised
        original = mat.get("original_name", canonical)
        formula = mat.get("formula", "")
        role = mat.get("role", "active_material")
        morphology = mat.get("morphology", "")
        is_electrolyte = mat.get("electrolyte", False)

        labels = "Material"
        if is_electrolyte:
            labels += ":Electrolyte"

        tx.run(
            f"""
            CREATE (m:{labels} {{
                material_id: $mat_id,
                name: $name,
                original_name: $original,
                chemical_formula: $formula,
                role: $role
            }})
            WITH m
            MATCH (p:PaperSource {{doi: $doi}})
            MERGE (m)-[:REPORTED_IN]->(p)
            """,
            mat_id=mat_id, name=canonical, original=original,
            formula=formula, role=role, doi=doi
        )

        # Morphology (if non‑empty)
        if morphology:
            tx.run(
                "MATCH (m:Material {material_id: $mat_id}) "
                "MERGE (morph:Morphology {description: $morph}) "
                "MERGE (m)-[:HAS_MORPHOLOGY]->(morph)",
                mat_id=mat_id, morph=morphology
            )

        # ----- Synthesis steps (if synthesis_route exists) -----
        synth = mat.get("synthesis_route")
        if synth:
            # Normalise to list of steps
            if isinstance(synth, list):
                step_list = synth
            else:
                step_list = [synth]

            previous_step_id = None
            first_step_id = None   # will store first step_id for later use (if needed)

            for i, step_data in enumerate(step_list, start=1):
                step_id = uid("step")
                if i == 1:
                    first_step_id = step_id

                method_name = step_data.get("method", "Unspecified") or []
                precursors = step_data.get("precursors", []) or []
                parameters = step_data.get("parameters", []) or []

                # Create step node and link to material, method, and paper
                tx.run(
                    "MATCH (paper:PaperSource {doi: $doi}) "
                    "CREATE (s:SynthesisStep {step_id: $step_id, order: $order, description: $desc}) "
                    "WITH s, paper "
                    "MATCH (m:Material {material_id: $mat_id}) "
                    "MERGE (m)-[:PRODUCED_BY]->(s) "
                    "CREATE (sm:SynthesisMethod {name: $method_name}) "
                    "MERGE (s)-[:USES_METHOD]->(sm) "
                    "MERGE (s)-[:REPORTED_IN]->(paper)",
                    doi=doi, step_id=step_id, order=i, desc=method_name,
                    mat_id=mat_id, method_name=method_name
                )

                # Chain to previous step
                if previous_step_id:
                    tx.run(
                        "MATCH (prev:SynthesisStep {step_id: $prev}) "
                        "MATCH (curr:SynthesisStep {step_id: $curr}) "
                        "MERGE (prev)-[:NEXT_STEP]->(curr)",
                        prev=previous_step_id, curr=step_id
                    )
                previous_step_id = step_id

                # Attach precursors for this step
                for precursor_name in precursors:
                    clean_name = re.sub(r'\s*\(.*?\)', '', precursor_name).strip()
                    role_hint = re.search(r'\((.*?)\)', precursor_name)
                    role_hint = role_hint.group(1) if role_hint else ""
                    tx.run(
                        "MATCH (s:SynthesisStep {step_id: $step_id}) "
                        "MATCH (paper:PaperSource {doi: $doi}) "
                        "MERGE (pc:Precursor {name: $clean_name}) "
                        "ON CREATE SET pc.original_name = $original_name, pc.role_hint = $role_hint "
                        "MERGE (s)-[:USES_PRECURSOR]->(pc) "
                        "MERGE (pc)-[:REPORTED_IN]->(paper)",
                        step_id=step_id, clean_name=clean_name,
                        original_name=precursor_name, role_hint=role_hint,
                        doi=doi
                    )

                # Attach parameters for this step
                for param in parameters:
                    p_name = param.get("parameter_name", "")
                    p_value = param.get("value", "")
                    p_unit = param.get("unit", "")
                    p_desc = param.get("description", "")
                    p_orig_unit = param.get("original_unit", "")
                    p_orig_value = param.get("original_value", "")
                    tx.run(
                        "MATCH (s:SynthesisStep {step_id: $step_id}) "
                        "CREATE (s)-[:HAS_PARAMETER]->(:Parameter {"
                        "  name: $name, "
                        "  value: $value, "
                        "  unit: $unit, "
                        "  description: $desc, "
                        "  original_unit: $orig_unit, "
                        "  original_value: $orig_value "
                        "})",
                        step_id=step_id, name=p_name, value=p_value,
                        unit=p_unit, desc=p_desc, orig_unit=p_orig_unit,
                        orig_value=p_orig_value
                    )

        # ----- Properties and test conditions -----
        for prop in (mat.get("performance_and_properties") or []):
            prop_id = uid("prop")
            p_name = prop["property_name"]           # canonical
            p_orig_name = prop.get("original_property_name", p_name)
            p_value = prop["value"]
            p_unit = prop.get("unit", "")
            p_orig_value = prop.get("original_value", p_value)
            p_orig_unit = prop.get("original_unit", p_unit)

            if isinstance(p_value, dict):
                p_value = json.dumps(p_value)
            if isinstance(p_orig_value, dict):
                p_orig_value = json.dumps(p_orig_value)

            # Create property node
            tx.run(
                "MATCH (paper:PaperSource {doi: $doi}) "
                "MATCH (m:Material {material_id: $mat_id}) "
                "CREATE (p:Property {"
                "  property_id: $prop_id, "
                "  property_name: $p_name, "
                "  original_property_name: $orig_name, "
                "  value: $value, "
                "  unit: $unit, "
                "  original_value: $orig_value, "
                "  original_unit: $orig_unit "
                "}) "
                "MERGE (m)-[:EXHIBITS_PROPERTY]->(p) "
                "MERGE (p)-[:REPORTED_IN]->(paper)",
                doi=doi, mat_id=mat_id, prop_id=prop_id, p_name=p_name,
                orig_name=p_orig_name, value=p_value, unit=p_unit,
                orig_value=p_orig_value, orig_unit=p_orig_unit
            )

            # Test conditions
            for cond in (prop.get("test_conditions", []) or []):
                c_name = cond.get("condition_name", "")      # canonical
                c_value = cond.get("value", "")      # string (often)
                c_unit = cond.get("unit", "")        # might be empty

                if not c_name:
                    c_name = cond.get("parameter_name", "")

                if c_name == "electrolyte":
                    orig, comps, solvent = parse_electrolyte_complex(c_value)
                    elec_id = uid("mat")
                    tx.run("""
                        MERGE (e:Electrolyte:Material {name: $name})
                        ON CREATE SET e.material_id = $elec_id, e.role = 'electrolyte',
                                    e.components_json = $comps_json, e.solvent = $solvent
                        ON MATCH SET e.components_json = $comps_json, e.solvent = $solvent
                        WITH e
                        MATCH (p:Property {property_id: $prop_id})
                        MATCH (paper:PaperSource {doi: $doi})
                        MERGE (p)-[:USING_ELECTROLYTE]->(e)
                        MERGE (e)-[:REPORTED_IN]->(paper)
                    """, name=orig, elec_id=elec_id, comps_json=json.dumps(comps), solvent=solvent,
                        prop_id=prop_id, doi=doi)
                else:
                    # Regular test condition
                    cond_id = uid("cond")
                    # Attempt to extract numeric value and unit if the value is like "1 A/g"
                    num_val, parsed_unit = extract_numeric_and_unit(c_value)
                    tx.run(
                        "MATCH (p:Property {property_id: $prop_id}) "
                        "CREATE (tc:TestCondition {"
                        "  condition_id: $cond_id, "
                        "  condition_name: $c_name, "
                        "  value: $val, "
                        "  unit: $unit, "
                        "  raw_value: $raw "
                        "}) "
                        "MERGE (p)-[:MEASURED_UNDER]->(tc)",
                        prop_id=prop_id, cond_id=cond_id, c_name=c_name,
                        val=num_val if num_val is not None else c_value,
                        unit=parsed_unit if parsed_unit else c_unit,
                        raw=c_value
                    )

import traceback

def main():
    count = 0

    START_FROM = "10.1016_j.electacta.2015.06.128.json"

    start_processing = False

    batch_size = 10

    with driver.session() as session:
        batch = []
        
        for fpath in glob.glob("outputs_json/*.json"):

            if not start_processing:
                if fpath.endswith(START_FROM):
                    start_processing = True
                else:
                    continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                doi = data.get("metadata", {}).get("doi", "UNKNOWN_DOI")
                title = data.get("metadata", {}).get("title", "UNKNOWN_TITLE")

                batch.append(data)
                if len(batch) >= batch_size:
                    session.execute_write(ingest_multiple_papers, batch)
                    batch = []

                # session.execute_write(ingest_paper, data)

                count += 1

                if count % 100 == 0:
                    print(f"Papers done: {count}")

            except Exception as e:
                print("\n" + "=" * 80)
                print("ERROR PROCESSING PAPER")
                print(f"File : {fpath}")
                print(f"DOI  : {doi}")
                print(f"Title: {title}")
                print(f"Error: {e}")
                print("=" * 80 + "\n")

                traceback.print_exc()

                break

        if batch:
            session.execute_write(ingest_multiple_papers, batch)

if __name__ == "__main__":
    main()