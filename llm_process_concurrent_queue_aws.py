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
os.environ['AWS_BEARER_TOKEN'] = ""
os.environ['AWS_ACCESS_KEY_ID']=""
os.environ['AWS_SECRET_ACCESS_KEY']=""
os.environ['AWS_DEFAULT_REGION']=""
MODEL_ID = 'openai.gpt-oss-120b-1:0'
REGION_NAME = "eu-north-1"

CONCURRENT_REQUESTS = 30
MAX_RETRIES = 3

# ----------------------------
# NORMALIZATION TASK CONFIG
# ----------------------------
BATCH_SIZE = 100               # names per LLM call
NAMES_INPUT_FILE = "material_names.json"
MAPPING_OUTPUT_FILE = "material_canonical_mapping_new.json"
PROGRESS_SAVE_INTERVAL = 30   # seconds


# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ----------------------------
# PROMPTS
# ----------------------------
SYSTEM_PROMPT = """
You are a materials science expert. You will receive a JSON array of material name strings.  
For each input string, apply the rules below to produce:
- "canonical_name": the standardised, clean chemical name.
- "electrolyte": true if the material is an electrolyte, otherwise false.

Rules for "canonical_name":
1. Strip all role words (binder, conductive additive, electrolyte, electrode, separator, substrate, current collector, etc.) and any surrounding punctuation. The canonical name must never contain a role.
2. Remove synthesis details (temperature, time, concentration, pH, CVD, etc.) unless they are an inseparable part of the material identity (e.g. “reduced graphene oxide” is fine, “CVD‑grown graphene” loses “CVD‑grown”).
3. Remove brand names / part numbers (e.g. “YP80F”, “BCAP3000”) if a generic chemical name can be given. For purely commercial products with no generic equivalent, keep the most descriptive product name.
4. Use standard IUPAC or universally accepted common names. Prefer the full systematic name over an acronym unless the acronym is the only common identifier (e.g. “PEDOT:PSS” is acceptable).
5. For simple inorganic compounds, use the chemical formula as the canonical name (e.g. “Co3O4”, “MnO2”, “TiO2”). Do NOT include morphology (nanoparticles, nanosheets) in the canonical name.
6. For composite materials (containing "/", "@", "-", "+"), keep the full composite expression in the most standard form (e.g. “MnO2/rGO” → “MnO2/rGO”). Remove morphology / role words from the composite.
7. For carbon materials, use the standard names: “activated carbon”, “graphene oxide”, “reduced graphene oxide”, “carbon nanotubes”, “carbon black”, “graphite”. Do not append morphology.
8. Normalise word order: base material first, then form (e.g. “nickel foam” not “foam nickel”; “carbon fiber” not “fiber carbon”).
9. Remove redundant parentheses and acronym duplicates; keep one clear identifier.
10. If the input name is genuinely unintelligible or cannot be normalised, set "canonical_name" to the best‑guess cleaned string and "electrolyte" to false.

Rules for "electrolyte":
- Set to true if the material name indicates it is an electrolyte. Indicators include:
  * The word “electrolyte” appears (e.g. “KOH electrolyte”, “gel electrolyte”).
  * The material is a solution of a salt/acid/base commonly used as an electrolyte in supercapacitors (KOH, H₂SO₄, Na₂SO₄, LiCl, TEABF₄, etc.), an ionic liquid (EMIM BF₄), a gel polymer electrolyte (PVA/KOH, PVA/H₃PO₄), or a solid electrolyte.
  * If the name contains a concentration (e.g. “6 M KOH”) and the solute is a typical electrolyte, set true.
- Otherwise set to false. Purely solid materials (e.g. “nickel foam”, “graphene oxide”, “Co₃O₄”) are always false.

You MUST output ONLY a single JSON object. The keys of the JSON object must be exactly the input strings (do not alter them). The value for each key must be an object with the fields "canonical_name" (a string) and "electrolyte" (a boolean).  
Do not include any additional text, markdown fences, or explanations.

Example Input:
["rGO", "6 M KOH aqueous solution", "binder PVDF", "Co3O4 nanoparticles", "PVA/KOH gel electrolyte", "Nickel foam", "activated carbon YP80F"]

Example Output:
{
  "rGO": {"canonical_name": "reduced graphene oxide", "electrolyte": false},
  "6 M KOH aqueous solution": {"canonical_name": "KOH (6 M)", "electrolyte": true},
  "binder PVDF": {"canonical_name": "polyvinylidene fluoride", "electrolyte": false},
  "Co3O4 nanoparticles": {"canonical_name": "Co3O4", "electrolyte": false},
  "PVA/KOH gel electrolyte": {"canonical_name": "PVA/KOH gel electrolyte", "electrolyte": true},
  "Nickel foam": {"canonical_name": "nickel foam", "electrolyte": false},
  "activated carbon YP80F": {"canonical_name": "activated carbon", "electrolyte": false}
}
"""

USER_PROMPT_TEMPLATE = """
Now process the following input array and produce the required JSON object:


"""


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
async def process_batch(client, batch_names, batch_idx, semaphore, results_dict, lock, missing_list):
    """
    Send a batch of material names to the LLM and store the parsed mapping.
    results_dict is a shared dict (thread‑safe via asyncio) where we accumulate
    the canonical info.
    """
    # Build the prompt
    input_json_str = json.dumps(batch_names, ensure_ascii=False)
    user_prompt = USER_PROMPT_TEMPLATE + input_json_str

    result_text, error = await asyncio.wait_for(
        call_bedrock_async(client, SYSTEM_PROMPT, user_prompt, semaphore),
        timeout=180
    )

    if error:
        logging.error(f"Batch {batch_idx} failed: {error}")
        # Mark all names in this batch as failed (e.g., keep original as canonical, electrolyte false)
        for name in batch_names:
            results_dict[name] = {"canonical_name": name, "electrolyte": False, "error": error}
        return

    # Parse the returned JSON
    try:
        # Clean potential markdown fences
        json_str = re.sub(r"```json\s*|\s*```", "", result_text).strip()
        batch_result = json.loads(json_str)
        if not isinstance(batch_result, dict):
            raise ValueError("Output is not a JSON object")
    except Exception as e:
        logging.error(f"Batch {batch_idx} JSON parse error: {e}")
        for name in batch_names:
            results_dict[name] = {"canonical_name": name, "electrolyte": False, "error": str(e)}
        return

    # Validate and store results
    async with lock:
        for name in batch_names:
            if name in batch_result:
                item = batch_result[name]
                canonical = item.get("canonical_name", name)
                electrolyte = item.get("electrolyte", False)
                results_dict[name] = {"canonical_name": canonical, "electrolyte": electrolyte}
            else:
                logging.warning(f"Batch {batch_idx}: missing key '{name}'")
                missing_list.append((batch_idx, name))


async def batch_worker(queue, client, semaphore, results, lock, missing_list):
    """Worker that processes batches from the queue."""
    while True:
        batch, idx = await queue.get()
        try:
            await process_batch(client, batch, idx, semaphore, results, lock, missing_list)
        except Exception as e:
            logging.error(f"Worker crashed on batch {idx}: {e}")
        finally:
            queue.task_done()

# ----------------------------
# MAIN ORCHESTRATOR
# ----------------------------
async def main():
    results_lock = asyncio.Lock()
    missing_names = []

    # Load the list of unique material names
    with open(NAMES_INPUT_FILE, "r", encoding="utf-8") as f:
        all_names = json.load(f)   # list of strings

    logging.info(f"Loaded {len(all_names)} unique material names.")
    
    # Split into batches
    batches = []
    for i in range(0, len(all_names), BATCH_SIZE):
        batch = all_names[i:i + BATCH_SIZE]
        batches.append(batch)
    
    total_batches = len(batches)
    logging.info(f"Total batches: {total_batches} (size {BATCH_SIZE}).")

    # Shared results dictionary (thread‑safe for asyncio tasks)
    results = {}

    missing_file = "missing_material_names.json"

    # Semaphore for concurrency
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    # Build a queue of tasks
    queue = asyncio.Queue()
    for idx, batch in enumerate(batches):
        await queue.put((batch, idx))

    bedrock_config = Config(
        connect_timeout=10,
        read_timeout=300,
        retries={'max_attempts': 0}
    )

    session = aioboto3.Session()
    async with session.client("bedrock-runtime", region_name=REGION_NAME, config=bedrock_config) as client:
        workers = []
        for _ in range(CONCURRENT_REQUESTS):
            workers.append(asyncio.create_task(
                batch_worker(queue, client, semaphore, results, results_lock, missing_names)
            ))

        # Periodically save progress
        async def progress_saver():
            while not queue.empty():
                await asyncio.sleep(PROGRESS_SAVE_INTERVAL)
                async with results_lock:
                    # Save the current results atomically
                    temp_path = MAPPING_OUTPUT_FILE + ".tmp"
                    with open(temp_path, "w", encoding="utf-8") as f:
                        json.dump(results, f, ensure_ascii=False, indent=2)
                    os.replace(temp_path, MAPPING_OUTPUT_FILE)

                    missing_temp = missing_file + ".tmp"
                    with open(missing_temp, "w", encoding="utf-8") as f:
                        json.dump(missing_names, f, ensure_ascii=False, indent=2)
                    os.replace(missing_temp, missing_file)

                    logging.info(f"Progress saved: {len(results)} names processed.")

        saver_task = asyncio.create_task(progress_saver())

        # Wait until all batches are processed
        await queue.join()

        # Cancel the saver
        saver_task.cancel()
        for w in workers:
            w.cancel()
        await asyncio.gather(saver_task, *workers, return_exceptions=True)

        # Final save
        with open(MAPPING_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logging.info(f"Mapping saved to {MAPPING_OUTPUT_FILE} ({len(results)} names).")

        with open(missing_file, "w", encoding="utf-8") as f:
            json.dump(missing_names, f, ensure_ascii=False, indent=2)
        logging.info(f"Missing keys saved to {missing_file} ({len(missing_names)} names).")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Catching the outer interrupt to prevent ugly stack traces
        logging.info("Program stopped by user (Ctrl+C).")