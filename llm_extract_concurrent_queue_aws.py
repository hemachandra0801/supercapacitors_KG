import asyncio
import aioboto3
import json
import os
import pandas as pd
import re
import logging
from botocore.exceptions import ClientError
from botocore.config import Config

# ----------------------------
# CONFIG
# ----------------------------
os.environ['AWS_BEARER_TOKEN_BEDROCK'] = ""
os.environ['AWS_ACCESS_KEY_ID']=""
os.environ['AWS_SECRET_ACCESS_KEY']=""
os.environ['AWS_DEFAULT_REGION']=""
MODEL_ID = 'openai.gpt-oss-20b-1:0'
REGION_NAME = "eu-north-1"

CONCURRENT_REQUESTS = 30
MAX_RETRIES = 3
INPUT_FOLDER = "json_papers"
OUTPUT_JSON = "outputs_json"
OUTPUT_RAW = "outputs_raw"
CSV_FILE = "supercapacitors_final.csv"

# Setup directories
for d in [OUTPUT_JSON, OUTPUT_RAW]: os.makedirs(d, exist_ok=True)

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ----------------------------
# PROMPTS
# ----------------------------
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

# --- SAVING FUNCTION ---
def safe_save_csv(df, path):
    """Saves to a temp file first, then renames to prevent corruption."""
    temp_path = path + ".tmp"
    try:
        df.to_csv(temp_path, index=False)
        if os.path.exists(temp_path):
            os.replace(temp_path, path) # Atomic swap on Linux/Windows
            logging.info(f"Progress safely backed up to {path}")
    except Exception as e:
        logging.error(f"Failed to save CSV: {e}")


async def worker(queue, client, df, semaphore):
    """Independent worker that pulls tasks from the queue."""
    while True:
        # Get a "task" (filename, index) from the queue
        fname, idx = await queue.get()
        try:
            await process_file(client, fname, idx, semaphore, df)
        except Exception as e:
            logging.error(f"Worker crashed on {fname}: {e}")
        finally:
            # Notify the queue that the task is done
            queue.task_done()

# ----------------------------
# ASYNC API CALL WITH BACKOFF
# ----------------------------
async def call_bedrock_async(client, system_prompt, user_prompt, semaphore):

    # Bedrock Payload Structure
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0
    }

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.invoke_model(
                    modelId=MODEL_ID,
                    body=json.dumps(payload)
                )
                
                # Bedrock returns a 'StreamingBody', we must read and decode it
                response_body = json.loads(await response['body'].read())
                content = response_body['choices'][0]['message']['content'].strip()

                clean_content = re.sub(r"<reasoning>.*?</reasoning>", "", content, flags=re.DOTALL).strip()
                
                # Clean JSON extraction logic
                json_match = re.search(r"```json\s*(.*?)\s*```", clean_content, re.DOTALL)
                if json_match:
                    return json_match.group(1).strip(), None
                
                brace_match = re.search(r"(\{.*\})", clean_content, re.DOTALL)
                return brace_match.group(1) if brace_match else clean_content, None

            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code in ['ThrottlingException', '429']:
                    wait_time = (2 ** attempt) + 2
                    logging.warning(f"Rate limited ({error_code}). Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    return None, f"AWS Error: {str(e)}"
            except Exception as e:
                logging.error(f"Request Error: {e}")
                await asyncio.sleep(2)
        
        return None, "Max retries exceeded"

# ----------------------------
# FILE PROCESSOR
# ----------------------------
async def process_file(client, filename, df_row_idx, semaphore, df_ref):
    doi = filename.replace(".json", "").replace("_", "/")
    filepath = os.path.join(INPUT_FOLDER, filename)
    output_name = filename.replace(".json", "")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            paper_json = json.load(f)
        
        user_prompt = USER_PROMPT_TEMPLATE + json.dumps(paper_json) + JSON_SCHEMA_TEMPLATE
        
        result, error = await asyncio.wait_for(
            call_bedrock_async(client, SYSTEM_PROMPT, user_prompt, semaphore), 
            timeout=180
        )

        if error:
            logging.error(f"Failed {doi}: {error}")
            with open(f"{OUTPUT_RAW}/{output_name}.txt", "w", encoding="utf-8") as f:
                f.write(f"Error: {error}")
            df_ref.at[df_row_idx, "llm_processed"] = 2
        else:
            try:
                parsed = json.loads(result)
                with open(f"{OUTPUT_JSON}/{output_name}.json", "w", encoding="utf-8") as f:
                    json.dump(parsed, f, indent=2, ensure_ascii=False)
                df_ref.at[df_row_idx, "llm_processed"] = 1
                logging.info(f"Success: {doi}")
            except:
                with open(f"{OUTPUT_RAW}/{output_name}.txt", "w", encoding="utf-8") as f:
                    f.write(result)
                df_ref.at[df_row_idx, "llm_processed"] = 2
                logging.error(f"Invalid JSON: {doi}")

    except asyncio.TimeoutError:
        logging.error(f"Individual Timeout: {doi} skipped. Other workers continuing...")
        df_ref.at[df_row_idx, "llm_processed"] = 3 # Mark as timeout
    except Exception as e:
        logging.error(f"File Error {filename}: {e}")

# ----------------------------
# MAIN ORCHESTRATOR
# ----------------------------
async def main():
    # Load and clean CSV
    df = pd.read_csv(CSV_FILE)
    
    doi_to_index = {doi: idx for idx, doi in enumerate(df["doi"])}
    files = [f for f in os.listdir(INPUT_FOLDER) if f.endswith(".json")]
    
    # Semaphore handles the concurrency "width"
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    # Filter tasks
    tasks_to_run = []
    for f in files:
        doi = f.replace(".json", "").replace("_", "/")
        if doi in doi_to_index and df.at[doi_to_index[doi], "llm_processed"] != 1:
            # We store the call in a list
            tasks_to_run.append((f, doi_to_index[doi]))
    
    total = len(tasks_to_run)
    logging.info(f"Starting processing for {total} tasks with {CONCURRENT_REQUESTS} workers...")

    #CREATE THE QUEUE
    queue = asyncio.Queue()
    for task in tasks_to_run:
        await queue.put(task)

    bedrock_config = Config(
        connect_timeout=10,
        read_timeout=300, # Increased from default
        retries={'max_attempts': 0} # We handle retries in our own loop
    )

    session = aioboto3.Session()
    async with session.client("bedrock-runtime", region_name=REGION_NAME, config=bedrock_config) as client:
        try:

            workers = []
            for _ in range(CONCURRENT_REQUESTS):
                workers.append(asyncio.create_task(worker(queue, client, df, semaphore)))

            while not queue.empty():
                await asyncio.sleep(60)
                safe_save_csv(df, CSV_FILE) # Save every 30 seconds
                logging.info(f"Queue size: {queue.qsize()} tasks remaining...")

            # Wait until all items in the queue are processed
            await queue.join()

            # Stop workers
            for w in workers:
                w.cancel()

            # Wait for workers to actually stop
            await asyncio.gather(*workers, return_exceptions=True)
            logging.info("All workers shut down. Processing complete.")

        except asyncio.CancelledError:
            logging.warning("Task cancellation requested (Ctrl+C captured)...")
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
        finally:
            logging.info("Finalizing and performing emergency save...")
            safe_save_csv(df, CSV_FILE)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Catching the outer interrupt to prevent ugly stack traces
        logging.info("Program stopped by user (Ctrl+C).")




































