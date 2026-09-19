import json
import os

def validate_bedrock_jsonl(filepath):
    print(f"Validating {filepath}...")
    errors = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                
                # Rule 1: Must have recordId
                if "recordId" not in data:
                    errors.append(f"Line {i}: Missing 'recordId'")
                
                # Rule 2: Must have modelInput
                if "modelInput" not in data:
                    errors.append(f"Line {i}: Missing 'modelInput'")
                else:
                    m_input = data["modelInput"]
                    # Rule 3: Check for messages structure (specific to Chat models)
                    if "messages" not in m_input:
                        errors.append(f"Line {i}: 'modelInput' missing 'messages' list")
                    
            except json.JSONDecodeError:
                errors.append(f"Line {i}: Invalid JSON syntax")

    if not errors:
        print("File looks perfect for Bedrock Batch!")
    else:
        print(f"Found {len(errors)} errors:")
        for err in errors[:10]:
            print(f"  - {err}")

if __name__ == "__main__":
    validate_bedrock_jsonl("bedrock_batch_input.jsonl")
