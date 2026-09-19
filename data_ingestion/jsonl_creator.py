import json, glob, re

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

# Pre-process each paper: add parsed fields so Cypher doesn't need complex logic
processed_dir = "outputs_json/"

# cnt = 0

with open("papers.jsonl", "w", encoding="utf-8") as out:
    for fpath in glob.glob("outputs_json/*.json"):
        with open(fpath, 'r', encoding="utf-8") as f:
            paper = json.load(f)

        # Pre-process test conditions: parse electrolytes and numerics
        for mat in (paper.get("materials", []) or []):
            for prop in (mat.get("performance_and_properties", []) or []):
                for cond in (prop.get("test_conditions", []) or []):
                    if cond.get("condition_name", "") == "electrolyte":
                        orig, comps, solvent = parse_electrolyte_complex(cond.get("value", ""))
                        cond["electrolyte_original"] = orig
                        cond["electrolyte_components"] = comps   # list of dicts
                        cond["electrolyte_solvent"] = solvent
                    else:
                        num, unit = extract_numeric_and_unit(cond.get("value", ""))
                        cond["numeric_value"] = num if num is not None else cond.get("value", "")
                        cond["parsed_unit"] = unit if unit else ""
            # Pre-process precursors: split role hints
            synth = mat.get("synthesis_route")
            if synth:
                steps = [synth] if isinstance(synth, dict) else synth
                for step in steps:
                    cleaned_precursors = []
                    for prec in (step.get("precursors", []) or []):
                        clean = re.sub(r'\s*\(.*?\)', '', prec).strip()
                        role_match = re.search(r'\((.*?)\)', prec)
                        role = role_match.group(1) if role_match else ""
                        cleaned_precursors.append({
                            "clean_name": clean,
                            "original_name": prec,
                            "role": role
                        })
                    step["precursors_parsed"] = cleaned_precursors
            # Mark electrolyte materials with a flag (already have "electrolyte": true)

        out.write(json.dumps(paper) + "\n")
