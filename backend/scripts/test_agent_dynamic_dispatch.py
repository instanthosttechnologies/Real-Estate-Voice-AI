import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import sync_engine
from sqlalchemy.orm import sessionmaker
from app.services.agent.dispatcher import dispatch_agent_tool

def run():
    print("=== TESTING AGENT DISPATCHER WITH DYNAMIC DATASET ===")
    SyncSession = sessionmaker(bind=sync_engine)
    with SyncSession() as db:
        # Test 1: Calling query_active_dataset through agent dispatcher
        print("\nTest 1: Calling 'query_active_dataset' for DLF projects in Gurugram...")
        resp1 = dispatch_agent_tool(
            db=db,
            tool_name="query_active_dataset",
            raw_arguments={"query": "DLF residential projects in Gurugram", "developer": "DLF", "city": "Gurugram"}
        )
        print(f"Success: {resp1.success}")
        print(f"Data found: {resp1.data.get('found')}")
        print(f"Matches count: {resp1.data.get('total_matches')}")
        print(f"Voice Grounding: {resp1.data.get('voice_grounding')[:140]}...")
        assert resp1.success is True
        assert resp1.data.get("found") is True

        # Test 2: Calling search_properties through agent dispatcher (dataset-grounded fallback)
        print("\nTest 2: Calling 'search_properties' for Godrej in Mumbai...")
        resp2 = dispatch_agent_tool(
            db=db,
            tool_name="search_properties",
            raw_arguments={"company_name": "Godrej Properties", "city": "Mumbai", "limit": 3}
        )
        print(f"Success: {resp2.success}")
        print(f"Data: {resp2.data.get('dataset_name')}, Total Matches: {resp2.data.get('total_exact_matches')}")
        print(f"Voice Grounding: {resp2.data.get('voice_grounding')[:140]}...")
        assert resp2.success is True

        # Test 3: Anti-hallucination test on non-existent property
        print("\nTest 3: Calling 'query_active_dataset' for non-existent Atlantis project on Mars...")
        resp3 = dispatch_agent_tool(
            db=db,
            tool_name="query_active_dataset",
            raw_arguments={"query": "Atlantis underwater crystal tower on Mars"}
        )
        print(f"Success: {resp3.success}")
        print(f"Found: {resp3.data.get('found')}")
        print(f"Voice Grounding: {resp3.data.get('voice_grounding')}")
        assert resp3.data.get("found") is False
        assert "could not find properties matching" in resp3.data.get("voice_grounding")

        print("\nALL AGENT DISPATCHER DYNAMIC DATASET TESTS PASSED!")

if __name__ == "__main__":
    run()
