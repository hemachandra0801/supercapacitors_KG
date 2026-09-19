import xml.etree.ElementTree as ET

# ----------------------------
# Namespace mapping
# ----------------------------
NS = {
    'default': 'http://www.elsevier.com/xml/svapi/article/dtd',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
    'ce': 'http://www.elsevier.com/xml/common/dtd',
    'xocs': 'http://www.elsevier.com/xml/xocs/dtd',
    'prism': 'http://prismstandard.org/namespaces/basic/2.0/',
    'tb': 'http://www.elsevier.com/xml/common/table/dtd',
    'cals': 'http://www.elsevier.com/xml/common/cals/dtd'
}

# ----------------------------
# Utility functions
# ----------------------------
def parse_mathml(node):
    tag = strip_ns(node.tag)

    # ----------------------------
    # BASE CASES
    # ----------------------------
    if tag in ['mi', 'mn']:
        return node.text.strip() if node.text else ""

    if tag == 'mo':
        return node.text.strip() if node.text else ""

    # ----------------------------
    # SUBSCRIPT
    # ----------------------------
    if tag == 'msub':
        children = list(node)
        if len(children) >= 2:
            base = parse_mathml(children[0])
            sub = parse_mathml(children[1])
            return f"{base}_{sub}"

    # ----------------------------
    # SUPERSCRIPT
    # ----------------------------
    if tag == 'msup':
        children = list(node)
        if len(children) >= 2:
            base = parse_mathml(children[0])
            sup = parse_mathml(children[1])
            return f"{base}^{sup}"

    # ----------------------------
    # FRACTION
    # ----------------------------
    if tag == 'mfrac':
        children = list(node)
        if len(children) == 2:
            num = parse_mathml(children[0])
            den = parse_mathml(children[1])
            return f"({num})/({den})"

    # ----------------------------
    # ROW (SEQUENCE)
    # ----------------------------
    if tag == 'mrow':
        return ''.join(parse_mathml(child) for child in node)

    # ----------------------------
    # ROOT <math>
    # ----------------------------
    if tag == 'math':
        return ''.join(parse_mathml(child) for child in node)

    # ----------------------------
    # FALLBACK
    # ----------------------------
    return ''.join(parse_mathml(child) for child in node)

def get_text(elem):
    """Safely extract text"""
    return elem.text.strip() if elem is not None and elem.text else None

def get_all_text(elem):
    """Extract full text recursively (handles nested tags)"""
    if elem is None:
        return None
    return ''.join(elem.itertext()).strip()

def get_all_text_clean(elem):
    if elem is None:
        return ""

    parts = []

    # ----------------------------
    # TEXT BEFORE CHILDREN
    # ----------------------------
    if elem.text:
        parts.append(elem.text)

    # ----------------------------
    # PROCESS CHILDREN
    # ----------------------------
    for child in elem:
        tag = strip_ns(child.tag)

        # ----------------------------
        # MATHML HANDLING
        # ----------------------------
        if tag == 'math':
            parts.append(f"[MATH:{parse_mathml(child)}]")

        # ----------------------------
        # SUPERSCRIPT
        # ----------------------------
        elif tag == 'sup':
            if child.text:
                parts.append(f"^{child.text}")

        # ----------------------------
        # SUBSCRIPT (inf)
        # ----------------------------
        elif tag == 'inf':
            if child.text:
                parts.append(f"_{child.text}")

        # ----------------------------
        # NORMAL CHILD
        # ----------------------------
        else:
            parts.append(get_all_text_clean(child))

        # ----------------------------
        # TEXT AFTER CHILD
        # ----------------------------
        if child.tail:
            parts.append(child.tail)

    # ----------------------------
    # CLEANUP
    # ----------------------------
    text = ''.join(parts)
    text = ' '.join(text.split())  # normalize whitespace

    return text

def parse_section(sec):
    data = {}

    title_elem = sec.find('ce:section-title', NS)
    data['title'] = get_all_text_clean(title_elem)

    # Direct paragraphs only
    data['paragraphs'] = [
        get_all_text_clean(p) for p in sec.findall('ce:para', NS)
        if get_all_text_clean(p)
    ]

    # Recursive subsections
    data['subsections'] = [
        parse_section(child) for child in sec.findall('ce:section', NS)
    ]

    return data

def strip_ns(tag):
    """Remove namespace from tag"""
    return tag.split('}')[-1]


def parse_table(table):
    table_data = {}

    # ----------------------------
    # CAPTION
    # ----------------------------
    table_data['caption'] = None
    for elem in table.iter():
        if strip_ns(elem.tag) == 'caption':
            table_data['caption'] = get_all_text_clean(elem)
            break

    # ----------------------------
    # BUILD COLUMN MAP
    # ----------------------------
    colspec = []
    for elem in table.iter():
        if strip_ns(elem.tag) == 'colspec':
            name = elem.attrib.get('colname')
            if name:
                colspec.append(name)
    
    # Fallback if colspec missing entirely
    if not colspec:
        # infer from max columns seen (safe fallback)
        colspec = [f"col{i}" for i in range(20)]  # or dynamic

    col_index = {name: i for i, name in enumerate(colspec)}
    n_cols = len(colspec)

    # ----------------------------
    # HEADER GRID
    # ----------------------------
    header_grid = []

    thead = None
    for elem in table.iter():
        if strip_ns(elem.tag) == 'thead':
            thead = elem
            break

    if thead is not None:
        active_rowspans_header = {}

        for row in thead:
            if strip_ns(row.tag) != 'row':
                continue

            grid_row = [None] * n_cols
            col_pointer = 0

            # ----------------------------
            # APPLY PREVIOUS ROWSPANS
            # ----------------------------
            for col_idx in list(active_rowspans_header.keys()):
                value, remaining = active_rowspans_header[col_idx]
                grid_row[col_idx] = value

                if remaining > 1:
                    active_rowspans_header[col_idx] = (value, remaining - 1)
                else:
                    del active_rowspans_header[col_idx]

            for entry in row:
                if strip_ns(entry.tag) != 'entry':
                    continue

                text = get_all_text_clean(entry)

                # Handle colspan
                start = entry.attrib.get('namest') or entry.attrib.get('colname')
                end = entry.attrib.get('nameend') or start

                # ----------------------------
                # CASE 1: colspan
                # ----------------------------
                if start and end:
                    if start not in col_index:
                        # fallback to pointer
                        while col_pointer < n_cols and grid_row[col_pointer] is not None:
                            col_pointer += 1
                        start_idx = col_pointer
                        end_idx = col_pointer
                    else:
                        start_idx = col_index[start]
                        end_idx = col_index.get(end, start_idx)

                # ----------------------------
                # CASE 2: single column (explicit)
                # ----------------------------
                elif entry.attrib.get('colname'):
                    start_idx = col_index[entry.attrib['colname']]
                    end_idx = start_idx

                # ----------------------------
                # CASE 3: NO colname → use pointer
                # ----------------------------
                else:
                    while col_pointer < n_cols and grid_row[col_pointer] is not None:
                        col_pointer += 1

                    start_idx = col_pointer
                    end_idx = col_pointer

                if end_idx >= len(grid_row):
                    grid_row.extend([None] * (end_idx - len(grid_row) + 1))

                # Fill columns
                for i in range(start_idx, end_idx + 1):
                    grid_row[i] = text

                # ----------------------------
                # STORE ROWSPAN
                # ----------------------------
                morerows = int(entry.attrib.get('morerows', 0))
                if morerows > 0:
                    for i in range(start_idx, end_idx + 1):
                        active_rowspans_header[i] = (text, morerows)

                # Move pointer
                col_pointer = end_idx + 1

                # start_idx = col_index[start]
                # end_idx = col_index[end]

                # for i in range(start_idx, end_idx + 1):
                #     grid_row[i] = text

            header_grid.append(grid_row)

    # ----------------------------
    # MERGE HEADER LEVELS
    # ----------------------------
    final_headers = []

    for col in range(n_cols):
        seen = set()
        parts = []
        for row in header_grid:
            val = row[col]
            if val and val not in seen:
                parts.append(val)
                seen.add(val)

        final_headers.append(" - ".join(parts))

    table_data['headers'] = final_headers

    # ----------------------------
    # BODY ROWS
    # ----------------------------
    rows = []

    tbody = None
    for elem in table.iter():
        if strip_ns(elem.tag) == 'tbody':
            tbody = elem
            break

    # if tbody is not None:
    #     for row in tbody:
    #         if strip_ns(row.tag) != 'row':
    #             continue

    #         row_data = [None] * n_cols

    #         for entry in row:
    #             if strip_ns(entry.tag) != 'entry':
    #                 continue

    #             text = get_all_text_clean(entry)
    #             colname = entry.attrib.get('colname')

    #             if colname in col_index:
    #                 row_data[col_index[colname]] = text

    #         rows.append(row_data)

    active_rowspans = {}  # col_index -> (value, remaining_rows)

    if tbody is not None:
        for row in tbody:
            if strip_ns(row.tag) != 'row':
                continue

            row_data = [None] * n_cols

            # ----------------------------
            # Step 1: Fill from active rowspans
            # ----------------------------
            for col_idx in list(active_rowspans.keys()):
                value, remaining = active_rowspans[col_idx]
                row_data[col_idx] = value

                if remaining > 1:
                    active_rowspans[col_idx] = (value, remaining - 1)
                else:
                    del active_rowspans[col_idx]

            # ----------------------------
            # Step 2: Fill current row entries
            # ----------------------------
            col_pointer = 0

            for entry in row:
                if strip_ns(entry.tag) != 'entry':
                    continue

                text = get_all_text_clean(entry)
                # colname = entry.attrib.get('colname')

                # if colname not in col_index:
                #     continue

                # col_idx = col_index[colname]

                # # Place value
                # row_data[col_idx] = text

                if entry.attrib.get('colname'):
                    col_idx = col_index[entry.attrib['colname']]
                else:
                    # fallback
                    while col_pointer < n_cols and row_data[col_pointer] is not None:
                        col_pointer += 1
                    if col_pointer >= n_cols:
                        continue  # or expand dynamically
                    col_idx = col_pointer

                row_data[col_idx] = text

                col_pointer = col_idx + 1

                # Handle rowspan
                morerows = int(entry.attrib.get('morerows', 0))
                if morerows > 0:
                    active_rowspans[col_idx] = (text, morerows)

            rows.append(row_data)

    table_data['rows'] = rows

    return table_data

# ----------------------------
# Core parser
# ----------------------------
def parse_elsevier_xml(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    data = {}

    # ----------------------------
    # 1. CORE METADATA
    # ----------------------------
    core = root.find('default:coredata', NS)

    data['title'] = get_text(core.find('dc:title', NS))
    data['doi'] = get_text(core.find('prism:doi', NS))

    # Abstract
    data['abstract'] = get_all_text_clean(core.find('dc:description', NS))

    # Keywords
    data['keywords'] = [
        get_text(k) for k in core.findall('dcterms:subject', NS)
    ]

    # ----------------------------
    # 2. FULL TEXT (SECTIONS)
    # ----------------------------
    original_text = root.find('.//xocs:doc', NS)

    sections = []

    if original_text is not None:
        body = original_text.find('.//ce:sections', NS)

        if body is not None:
            section_elems = body.findall('ce:section', NS)

            # ----------------------------
            # CASE 1: Normal structured sections
            # ----------------------------
            if section_elems:
                sections = [parse_section(sec) for sec in section_elems]

            # ----------------------------
            # CASE 2: Flat paragraphs (your problematic paper)
            # ----------------------------
            else:
                paras = body.findall('ce:para', NS)

                if paras:
                    sections = [{
                        "title": None,
                        "paragraphs": [
                            get_all_text_clean(p) for p in paras if get_all_text_clean(p)
                        ],
                        "subsections": []
                    }]

    data['sections'] = sections

    # ----------------------------
    # 3. TABLES
    # ----------------------------
    tables = []

    for elem in root.iter():
        if strip_ns(elem.tag) == 'table':
            tables.append(parse_table(elem))

    data['tables'] = tables

    return data


import os
import json

INPUT_FOLDER = "./papers"
OUTPUT_FOLDER = "./json_papers"

def process_all_files():
    # Create output folder if it doesn't exist
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    count = 0

    for filename in os.listdir(INPUT_FOLDER):
        if filename.endswith(".xml"):
            input_path = os.path.join(INPUT_FOLDER, filename)

            # Parse XML
            try:
                parsed_data = parse_elsevier_xml(input_path)
            except Exception as e:
                print(f"Error processing file: {filename}")
                print(f"Full path: {input_path}")
                print(f"Error: {e}")
                continue

            if parsed_data["abstract"] == "Unknown" or parsed_data["sections"] is None:
                print(f"DOI: {parsed_data['doi']} not processed")
                continue

            # Create output file path with same name but .json extension
            base_name = os.path.splitext(filename)[0]
            output_filename = base_name + ".json"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)

            # Write JSON
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(parsed_data, f, indent=2, ensure_ascii=False)

            if count % 500 == 0:
                print(f"Processed: {count} papers")

            count += 1


# ----------------------------
# Usage
# ----------------------------
if __name__ == "__main__":
    # file_path = "./papers/10.1016_j.cej.2023.147805.xml"
    # parsed_data = parse_elsevier_xml(file_path)

    # import json
    # print(json.dumps(parsed_data, indent=2, ensure_ascii=False))

    process_all_files()
