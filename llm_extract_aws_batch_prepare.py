import os
import json
import pandas as pd
import logging

# ----------------------------
# CONFIG
# ----------------------------
CSV_FILE = "supercapacitors_final.csv"
INPUT_FOLDER = "json_papers"
BATCH_INPUT_FILE = "bedrock_batch_input.jsonl"
MODEL_ID = "openai.gpt-oss-20b-1:0"

# Prompt Templates
SYSTEM_PROMPT = """
You are an expert Materials Science AI Assistant specializing in electrochemical energy storage and materials informatics. Your task is to transform unstructured research paper content into a high-fidelity, structured JSON format suitable for Knowledge Graph population.

CRITICAL EXTRACTION RULES:

1. Experimental Data Only: Extract only experimentally measured values and synthesized materials. Do not include theoretical predictions, simulations, or literature review values unless they are the primary focus of the experiment.

2. Material Roles: For every material mentioned, identify its specific role in the device (e.g., "active_material", "electrolyte", "conductive_additive", "binder", "separator").

3. Interdependency (Property-Condition): You MUST link every performance metric (e.g., Specific Capacitance) to its specific test conditions (e.g., Current Density, Electrolyte, Voltage Window). Do not extract property values in isolation.

4. Flexible Synthesis: Do not look for a fixed set of parameters. Extract ALL reported synthesis variables (e.g., pH, stirring speed, hydrothermal pressure, annealing atmosphere, precursor concentrations) as key-value pairs.

5. Structural Integrity: Capture structural/physical properties like Specific Surface Area (BET), Pore Volume, and Pore Size, as these are critical for recommendation logic.

6. No Hallucinations: If a piece of information is missing, use null or an empty array ``. Never guess or fill in missing data based on general knowledge.

7. Standard Formulas: Ensure all chemical formulas are represented as clean strings (e.g., "NiCo2O4", "Ti3C2Tx").
"""

USER_PROMPT_TEMPLATE = """
Analyze the research paper content provided below. Extract the materials, synthesis protocols, and performance metrics into the provided JSON schema.

Return ONLY a valid JSON object.

RESEARCH PAPER CONTENT:


"""

JSON_SCHEMA_TEMPLATE = """

JSON SCHEMA TO FOLLOW:

{
  "type": "object",
  "properties": {
    "metadata": {
      "type": "object",
      "properties": {
        "doi": { "type": "string" },
        "title": { "type": "string" }
      }
    },
    "materials": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string", "description": "Full name or acronym, e.g., Reduced Graphene Oxide" },
          "formula": { "type": "string", "description": "Chemical formula, e.g., rGO" },
          "role": { 
            "type": "string", 
            "enum": ["active_material", "electrolyte", "separator", "binder", "conductive_additive", "substrate"] 
          },
          "morphology": { "type": "string", "description": "e.g., 3D hierarchical pores, nanosheets, nanowires" },
          "synthesis_route": {
            "type": "object",
            "properties": {
              "method": { "type": "string", "description": "Primary method, e.g., Hydrothermal, Sol-gel, Electrodeposition" },
              "precursors": { "type": "array", "items": { "type": "string" } },
              "parameters": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "parameter_name": { "type": "string", "description": "e.g., temperature, pH, aging_time, pressure" },
                    "value": { "type": "string" },
                    "unit": { "type": "string" }
                  }
                },
		            "description": "Capture all reported variables: temp, time, pH, stirring speed, pressure, etc."
              }
            }
          },
          "performance_and_properties": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "property_name": { "type": "string", "description": "e.g., specific_capacitance, energy_density, specific_surface_area, cycle_retention" },
                "value": { "type": "number" },
                "unit": { "type": "string", "description": "e.g., F/g, Wh/kg, m2/g, %" },
                "test_conditions": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "condition_name": { "type": "string", "description": "e.g., current_density, scan_rate, electrolyte, voltage_window" },
                      "value": { "type": "string" }
                    }
                  },
		              "description": "Include: electrolyte (6M KOH), current_density (1 A/g), voltage_window (0-1.0V), scan_rate (5 mV/s)"
                }
              }
            }
          }
        }
      }
    }
  },
  "required": ["metadata", "materials"]
}
"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def prepare_batch():
    # 1. Load CSV
    if not os.path.exists(CSV_FILE):
        logging.error(f"CSV file {CSV_FILE} not found.")
        return

    df = pd.read_csv(CSV_FILE)
    # Ensure llm_processed is numeric
    df['llm_processed'] = pd.to_numeric(df['llm_processed'], errors='coerce').fillna(0).astype(int)

    # 2. Identify files to process
    all_files = [f for f in os.listdir(INPUT_FOLDER) if f.endswith(".json")]
    
    # Create a mapping of DOI -> Index for quick lookup
    doi_to_index = {doi: idx for idx, doi in enumerate(df["doi"])}
    
    to_process = []
    
    for filename in all_files:
        # Get DOI from filename (replace _ with /)
        doi = filename.replace(".json", "").replace("_", "/")
        
        if doi in doi_to_index:
            idx = doi_to_index[doi]
            if df.at[idx, "llm_processed"] != 1:
                to_process.append((filename, doi))
        
    logging.info(f"Total papers found in folder: {len(all_files)}")
    logging.info(f"Papers remaining to process: {len(to_process)}")

    # 3. Create JSONL for Bedrock Batch
    test_batch = to_process[:200]
    logging.info(f"Preparing batch file with {len(test_batch)} records...")

    with open(BATCH_INPUT_FILE, "w", encoding="utf-8") as f_out:
        for filename, doi in test_batch:
            filepath = os.path.join(INPUT_FOLDER, filename)
            
            with open(filepath, "r", encoding="utf-8") as f_in:
                paper_content = json.load(f_in)

            user_message = USER_PROMPT_TEMPLATE + json.dumps(paper_content) + JSON_SCHEMA_TEMPLATE

            # Construct the request in the format Bedrock Batch expects
            record = {
                "recordId": filename.replace(".json", ""),
                "modelInput": {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.0
                }
            }
            f_out.write(json.dumps(record) + "\n")

    logging.info(f"Success! {BATCH_INPUT_FILE} is ready for upload to S3.")

if __name__ == "__main__":
    prepare_batch()



# import boto3
# import os

# os.environ['AWS_ACCESS_KEY_ID']=""
# os.environ['AWS_SECRET_ACCESS_KEY']=""
# os.environ['AWS_DEFAULT_REGION']=""

# # Create Bedrock client
# client = boto3.client("bedrock")

# # Unique job name
# job_name = f"ddp-project-1"

# response = client.create_model_invocation_job(
#     jobName=job_name,
    
#     # Role with permissions to access S3 + Bedrock
#     roleArn="arn:aws:iam::805865757931:role/BatchInferenceServiceRole",
    
#     # Input data configuration
#     inputDataConfig={
#         "s3InputDataConfig": {
#             "s3Uri": "s3://ddp-project/input/bedrock_batch_input.jsonl"
#         }
#     },
    
#     # Output location
#     outputDataConfig={
#         "s3OutputDataConfig": {
#             "s3Uri": "s3://ddp-project/output/"
#         }
#     },
    
#     # Model configuration
#     modelId="openai.gpt-oss-20b-1:0",
# )

# print("Job created!")
# print(response)