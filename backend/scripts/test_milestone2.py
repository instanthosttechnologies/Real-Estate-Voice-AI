import csv
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import sync_engine
from sqlalchemy.orm import sessionmaker
from app.services.dataset.manager import (
    activate_dataset,
    get_active_dataset,
    rollback_dataset,
    upload_and_import_dataset,
)
from app.services.dataset.retrieval import query_dynamic_dataset

def run():
    print("=== MILESTONE 2: DYNAMIC SCHEMA INGESTION & DATASET ISOLATION ===")

    # 1. Generate an entirely different schema dataset (Commercial Tech Parks)
    csv_rows = [
        ["PARK_CODE", "FACILITY_NAME", "METROPOLITAN_ZONE", "WORKSPACE_TIER", "LEASE_RATE_ANNUAL", "SUSTAINABILITY_RATING", "COLLABORATION_AMENITIES", "NETWORK_INFRASTRUCTURE"],
        ["TP_101", "Silicon Heights Innovation Center", "San Jose North", "Executive High-Tech Lab", "$65/sqft NNN", "LEED Zero Carbon", "Auditorium, 12 Podcasting Studios, Rooftop Solar Lounge", "Dual 40Gbps Dark Fiber Backbone"],
        ["TP_102", "Cyber Gateway Tower B", "Austin Silicon Hills", "Class-A Collaborative Loft", "$48/sqft Gross", "LEED Platinum", "VR Research Suite, 8 Boardrooms, Electric Fleet Chargers", "Redundant Tier-4 Datacenter Cross-connect"],
        ["TP_103", "Apex BioTech Campus", "Boston Seaport", "Wet Lab & Research Suites", "$85/sqft Full Service", "WELL Gold", "Cleanroom Class 1000, Cryo Storage, Nitrogen Generators", "Biometric Isolation, Dedicated Fiber Ring"],
        ["TP_104", "Quantum Horizon Tech Park", "Seattle Bellevue Tech Corridor", "Enterprise AI Development Suites", "$55/sqft NNN", "LEED Platinum", "200-seat amphitheater, AI server cooling loop, Zen Garden", "Direct AWS DirectConnect fiber drop"],
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_rows)
    csv_bytes = output.getvalue().encode("utf-8")

    SyncSession = sessionmaker(bind=sync_engine)
    with SyncSession() as db:
        print("\n1. Uploading and importing novel schema dataset (Commercial Tech Parks)...")
        new_ds = upload_and_import_dataset(
            db=db,
            file_bytes=csv_bytes,
            filename="Commercial_Tech_Parks.csv",
            auto_activate=True,
            dataset_name="Commercial Tech Parks"
        )
        print(f"Imported novel dataset: {new_ds.name} v{new_ds.version} (ID: {new_ds.id})")
        print(f"Total rows: {new_ds.total_rows}")
        print(f"Active status: {new_ds.is_active}")

        print("\n2. Inspecting detected schema in metadata registry:")
        cols = new_ds.metadata_registry["worksheets"]["Primary_Dataset"]["columns"]
        for c in cols:
            print(f"  - Column: {c['column_name']} | Type: {c['detected_type']} | Example: {c['example_values']}")

        print("\n3. Testing dynamic retrieval on the novel schema:")
        q1 = "Show me high tech labs with LEED Zero Carbon rating"
        res1 = query_dynamic_dataset(db, q1, limit=2)
        print(f"\nQuery 1: '{q1}'")
        print(f"Dataset active: {res1.get('dataset_name')}")
        print(f"Matches found: {res1.get('total_matches')}")
        print(f"Voice Grounding: {res1.get('voice_grounding')}")

        q2 = "Enterprise AI development suites in Seattle"
        res2 = query_dynamic_dataset(db, q2, limit=2)
        print(f"\nQuery 2: '{q2}'")
        print(f"Matches found: {res2.get('total_matches')}")
        print(f"Voice Grounding: {res2.get('voice_grounding')}")

        print("\n4. Verifying cross-dataset isolation:")
        q_leak = "Tell me about DLF The Camellias"
        res_leak = query_dynamic_dataset(db, q_leak, limit=2)
        print(f"Leakage test query: '{q_leak}'")
        print(f"Matches from Commercial Tech Parks: {res_leak.get('total_matches')}")
        assert res_leak.get("total_matches") == 0, "Zero leakage: DLF must NOT appear in Commercial Tech Parks dataset!"
        print("PASS: Zero records leaked from previous real estate dataset.")

        print("\n5. Testing Rollback functionality:")
        rollback_info = rollback_dataset(db, new_ds.id)
        print(f"Rollback result: {rollback_info}")

        # If previous was another version of Tech Parks, roll it back or activate Master Portfolio
        active_now = get_active_dataset(db)
        if active_now and active_now.name != "Real Estate Master Portfolio":
            rollback_dataset(db, active_now.id)

        active_after_rollback = get_active_dataset(db)
        print(f"Active dataset after rollback: {active_after_rollback.name} v{active_after_rollback.version}")
        assert active_after_rollback.name == "Real Estate Master Portfolio", "Must revert to Real Estate Master Portfolio"

        # Query again after rollback to confirm master portfolio is active
        res_after = query_dynamic_dataset(db, "DLF projects in Gurugram", limit=2)
        print(f"Query after rollback: Found {res_after.get('total_matches')} matches in '{res_after.get('dataset_name')}'.")
        assert res_after.get("total_matches") > 0, "Must successfully query restored Master Portfolio!"
        print("PASS: Rollback restored previous dataset with full fidelity.")

if __name__ == "__main__":
    run()
