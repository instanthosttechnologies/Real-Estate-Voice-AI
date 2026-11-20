import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import sync_engine
from sqlalchemy.orm import sessionmaker
from app.services.dataset.manager import upload_and_import_dataset, get_active_dataset
from app.services.dataset.retrieval import query_dynamic_dataset

def run():
    SyncSession = sessionmaker(bind=sync_engine)
    with SyncSession() as db:
        with open("Real_Estate_Dataset.xlsx", "rb") as f:
            content = f.read()

        print("1. Importing Real_Estate_Dataset.xlsx with auto_activate=True...")
        ds = upload_and_import_dataset(
            db=db,
            file_bytes=content,
            filename="Real_Estate_Dataset.xlsx",
            auto_activate=True,
            dataset_name="Real Estate Master Portfolio"
        )
        print(f"Imported dataset: {ds.name} v{ds.version} (ID: {ds.id})")
        print(f"Total records in primary sheet ({ds.primary_sheet}): {ds.total_rows}")
        print(f"Is active: {ds.is_active}")

        print("\n2. Verifying active dataset retrieval...")
        active = get_active_dataset(db)
        assert active is not None, "Active dataset must not be None"
        print(f"Active dataset name: {active.name}, Version: {active.version}")

        # Test Milestone 1 Queries
        test_queries = [
            ("Developers & Cities", "Tell me about DLF projects in Gurugram"),
            ("Configuration & Luxury", "Looking for 3BHK or 4BHK luxury residences by DLF"),
            ("Specific Developer", "What projects are available from Godrej Properties?"),
            ("City Filter", "Show me residential properties in Mumbai"),
            ("Amenities Grounding", "Tell me about projects with golf course access"),
            ("Commercial / Asset Type", "Commercial offices in Chennai"),
        ]

        print("\n3. Executing Milestone 1 Verification Queries:")
        for category, q in test_queries:
            res = query_dynamic_dataset(db, q, limit=2)
            print(f"\n--- Category: {category} | Query: '{q}' ---")
            print(f"Found: {res.get('found')}, Total Matches: {res.get('total_matches')}")
            print(f"Voice Grounding: {res.get('voice_grounding')[:150]}...")
            if res.get("records"):
                top = res["records"][0]
                print(f"Top Record ID: {top.get('record_id')}, Relevancy Score: {top.get('relevance_score')}")

if __name__ == "__main__":
    run()
