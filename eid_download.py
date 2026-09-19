# scopus_complete_pipeline.py
import requests
import time
import pandas as pd
from typing import List, Dict, Optional
import json

class ScopusDirectPipeline:
    """
    Complete pipeline for fetching Scopus data
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.search_url = "https://api.elsevier.com/content/search/scopus"
        self.abstract_url = "https://api.elsevier.com/content/abstract/eid/"
        self.headers = {
            'X-ELS-APIKey': api_key,
            'Accept': 'application/json'
        }

    def search_papers(self, query: str, max_results=None, delay: float = 0.5):

        all_entries = []
        cursor = "*"
        count = 25

        print(f"\nSearching: {query}")

        while cursor:

            params = {
                "query": query,
                "cursor": cursor,
                "count": count,
                "view": "COMPLETE"
            }

            response = requests.get(
                self.search_url,
                headers=self.headers,
                params=params
            )

            if response.status_code != 200:
                print(f"Error {response.status_code}")
                print(response.text)
                break

            data = response.json()
            results = data.get("search-results", {})
            entries = results.get("entry", [])

            if not entries:
                break

            all_entries.extend(entries)

            print(f"Fetched {len(all_entries)} records so far...")

            if max_results and len(all_entries) >= max_results:
                all_entries = all_entries[:max_results]
                break

            cursor = results.get("cursor", {}).get("@next")

            time.sleep(delay)

        records = []
        for entry in all_entries:
            records.append({
                "eid": entry.get("eid"),
                "doi": entry.get("prism:doi"),
                "title": entry.get("dc:title"),
                "publication_name": entry.get("prism:publicationName"),
                "cover_date": entry.get("prism:coverDate"),
                "citedby_count": entry.get("citedby-count", 0),
                "open_access": entry.get("openaccess", "0"),
            })

        return pd.DataFrame(records)
    
    def get_paper_details(self, eid: str) -> Dict:
        """
        Get detailed metadata for a specific EID
        """
        url = f"{self.abstract_url}{eid}"
        params = {'view': 'FULL'}
        
        try:
            response = requests.get(
                url, 
                headers=self.headers, 
                params=params
            )
            
            if response.status_code != 200:
                return {'eid': eid, 'error': f'HTTP {response.status_code}'}
            
            data = response.json()
            abstract_data = data.get('abstracts-retrieval-response', {})
            coredata = abstract_data.get('coredata', {})
            
            # Extract authors
            authors = []
            author_group = abstract_data.get('authors', {}).get('author', [])
            if isinstance(author_group, list):
                for author in author_group:
                    if isinstance(author, dict):
                        name = author.get('ce:indexed-name', '')
                        if name:
                            authors.append(name)
            
            # Extract abstract
            abstract_text = None
            if 'dc:description' in coredata:
                abstract_text = coredata['dc:description']
            elif 'abstract' in coredata:
                abstract_text = coredata['abstract']
            
            return {
                'eid': eid,
                'doi': coredata.get('prism:doi'),
                'title': coredata.get('dc:title'),
                'abstract': abstract_text,
                'authors': '; '.join(authors[:10]),
                'author_count': len(authors),
                'publication_name': coredata.get('prism:publicationName'),
                'volume': coredata.get('prism:volume'),
                'issue': coredata.get('prism:issueIdentifier'),
                'pages': coredata.get('prism:pageRange'),
                'cover_date': coredata.get('prism:coverDate'),
                'citedby_count': coredata.get('citedby-count', 0),
                'open_access': coredata.get('openaccess', '0'),
                'publisher': coredata.get('dc:publisher'),
            }
            
        except Exception as e:
            return {'eid': eid, 'error': str(e)}
    
    def process_papers(self, 
                      eids: List[str], 
                      output_file: str = "scopus_papers.csv",
                      batch_size: int = 10,
                      delay: float = 1.0):
        """
        Process multiple papers and save results
        """
        print(f"\n📊 Processing {len(eids)} papers...")
        
        results = []
        
        for idx, eid in enumerate(eids):
            print(f"  Processing {idx+1}/{len(eids)}: {eid[:15]}...")
            
            details = self.get_paper_details(eid)
            results.append(details)
            
            # Save intermediate results
            if (idx + 1) % batch_size == 0:
                temp_df = pd.DataFrame(results)
                temp_df.to_csv(f"temp_{idx+1}.csv", index=False)
                print(f"  💾 Saved {idx+1} results")
            
            time.sleep(delay)
        
        # Save final results
        df = pd.DataFrame(results)
        df.to_csv(output_file, index=False)
        
        print(f"\n✅ All results saved to {output_file}")
        
        # Summary
        success = df[df['error'].isna() if 'error' in df.columns else df.index]
        print(f"\n📊 Summary:")
        print(f"  Total processed: {len(df)}")
        print(f"  Successful: {len(success)}")
        if len(success) > 0:
            print(f"  With abstract: {success['abstract'].notna().sum()}")
            print(f"  Open access: {success['open_access'].eq('1').sum() if 'open_access' in success else 0}")
        
        return df

def main():
    API_KEY = ""
    
    # Initialize pipeline
    pipeline = ScopusDirectPipeline(API_KEY)
    
    print("=" * 60)
    print("Scopus Direct API Pipeline")
    print("=" * 60)

    all_df = pd.DataFrame()

    years = range(2018, 2027)

    all_results = []

    for year in years:
        print(f"\nProcessing year {year}")

        query = f"""
        (TITLE-ABS-KEY(supercapacitor*) OR TITLE-ABS-KEY(ultracapacitor*))
        AND PUBYEAR = {year}
        """

        df_year = pipeline.search_papers(query)

        print(f"Year {year}: {len(df_year)} papers")

        # append to master dataframe
        all_df = pd.concat([all_df, df_year], ignore_index=True)

        # remove duplicates
        all_df = all_df.drop_duplicates(subset="eid")

        # save progress after each year
        all_df.to_csv("scopus_eids_all_years.csv", index=False)

        print(f"Total collected so far: {len(all_df)}")


if __name__ == "__main__":
    main()
