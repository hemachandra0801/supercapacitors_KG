import pandas as pd
import requests
import time
import os
from threading import Lock, Semaphore
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import deque

# ================= CONFIGURATION =================
API_KEY = ""
INST_TOKEN = ""
MAX_REQUESTS_PER_SECOND = 8
MAX_WORKERS = 10
CSV_FILE = "supercapacitors_final.csv"
XML_DIR = "papers"
# =================================================

class SlidingWindowRateLimiter:
    """Enforce a maximum number of requests per second using a sliding window."""
    def __init__(self, rate):
        self.rate = rate
        self.window = deque()
        self.lock = Lock()

    def acquire(self):
        """Blocks until a request slot is available."""
        with self.lock:
            now = time.time()
            # Remove timestamps older than 1 second
            while self.window and now - self.window[0] > 1.0:
                self.window.popleft()

            # If we haven't reached the rate limit, allow immediately
            if len(self.window) < self.rate:
                self.window.append(now)
                return

            # Otherwise, wait until the oldest timestamp expires
            wait = self.window[0] + 1.0 - now
            if wait > 0:
                time.sleep(wait)

            # After waiting, add the new timestamp and allow
            now = time.time()
            # Clean up again (there may be more expired timestamps)
            while self.window and now - self.window[0] > 1.0:
                self.window.popleft()
            self.window.append(now)

# Global rate limiter
rate_limiter = SlidingWindowRateLimiter(MAX_REQUESTS_PER_SECOND)

def download_one(doi, idx, total, df):
    """Download a single paper, respecting rate limit."""
    if pd.isna(doi):
        return idx, 2, "DOI is NaN"

    url = f"https://api.elsevier.com/content/article/doi/{doi}"
    headers = {
        "X-ELS-APIKey": API_KEY,
        "X-ELS-Insttoken": INST_TOKEN,
        "Accept": "application/xml"
    }
    params = {"view": "FULL"}

    # Wait for a token (this ensures we never exceed rate)
    rate_limiter.acquire()

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
    except Exception as e:
        return idx, 2, str(e)

    if r.status_code == 200:
        safe_filename = doi.replace('/', '_').replace(':', '_')
        filepath = os.path.join(XML_DIR, f"{safe_filename}.xml")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(r.text)
        # print(f"✓ [{idx+1}/{total}] {doi}")
        return idx, 1, filepath
    if r.status_code == 429:
        print(f"✗ [{idx+1}/{total}] {doi} - Status {r.status_code}")
        return idx, 3, f"HTTP {r.status_code}"
    else:
        print(f"✗ [{idx+1}/{total}] {doi} - Status {r.status_code}")
        return idx, 2, f"HTTP {r.status_code}"

def main():
    # Read CSV
    df = pd.read_csv(CSV_FILE)

    # Create directory for XML files
    os.makedirs(XML_DIR, exist_ok=True)

    # Identify rows that need downloading (not yet downloaded and DOI not NaN)
    to_download = [(idx, row['doi']) for idx, row in df.iterrows()
                   if row['downloaded'] == 0 and pd.notna(row['doi'])]

    print(f"Total rows: {len(df)}")
    print(f"Already downloaded: {(df['downloaded'] == 1).sum()}")
    print(f"Failed earlier: {(df['downloaded'] == 2).sum()}")
    print(f"To download now: {len(to_download)}")
    print(f"Rate limit: {MAX_REQUESTS_PER_SECOND} req/sec, workers: {MAX_WORKERS}\n")

    if not to_download:
        print("No new papers to download.")
        return

    # Submit all tasks
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_one, doi, idx, len(to_download), df): idx
            for idx, doi in to_download
        }

        completed = 0
        for future in as_completed(futures):
            idx, status, msg = future.result()
            df.at[idx, 'downloaded'] = status
            completed += 1

            # Save progress every 50 downloads
            if completed % 50 == 0:
                df.to_csv(CSV_FILE, index=False)
                print(f"\n--- Progress saved after {completed}/{len(to_download)} ---\n")

    # Final save
    df.to_csv(CSV_FILE, index=False)

    # Summary
    print("\n" + "="*50)
    print("DOWNLOAD COMPLETE")
    print(f"Successfully downloaded: {(df['downloaded'] == 1).sum()}")
    print(f"Failed: {(df['downloaded'] == 2).sum()}")
    print("="*50)

if __name__ == "__main__":
    main()