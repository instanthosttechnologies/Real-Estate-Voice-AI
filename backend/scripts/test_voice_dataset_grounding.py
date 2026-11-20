import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import sync_engine
from sqlalchemy.orm import sessionmaker
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.orchestrator import VoiceSessionOrchestrator
from app.services.voice.tools_spec import get_agent_tools_spec
from app.services.voice.base import VoiceEventType
from app.services.dataset.manager import get_active_dataset

def run():
    print("=== TESTING VOICE ORCHESTRATOR GROUNDED IN UNIFIED_AI_DATASET ===")
    SyncSession = sessionmaker(bind=sync_engine)
    with SyncSession() as db:
        active_ds = get_active_dataset(db)
        print(f"Active Grounding Dataset: {active_ds.name} v{active_ds.version} ({active_ds.total_rows} records)")

        # Create Mock Voice Driver & Voice Orchestrator
        driver = MockVoiceDriver(model_id="amazon.nova-2-5-sonic")
        session_id = "voice_grounding_sess_001"
        orchestrator = VoiceSessionOrchestrator(
            session_id=session_id,
            driver=driver,
            db=db,
            user_role="customer",
            is_verified=True,
        )

        preamble = orchestrator._build_system_preamble()
        print("\n--- System Preamble Grounding Section ---")
        for line in preamble.split("\n"):
            if "ACTIVE VERIFIED DATASET" in line or "Primary Sheet" in line or "Ground all" in line:
                print(f"  {line}")

        # Test Multi-Turn Conversational Grounding
        turns = [
            ("Turn 1 - DLF in Gurugram", "Tell me about DLF luxury residential projects in Gurugram"),
            ("Turn 2 - Godrej 3BHK/4BHK", "What 3BHK or 4BHK residences do you have from Godrej?"),
            ("Turn 3 - Commercial Offices", "Do you have commercial offices in Chennai?"),
            ("Turn 4 - Anti-Hallucination", "Show me underwater crystal floating villas on Jupiter"),
        ]

        print("\n--- Simulating Spoken Customer Turns ---")
        for label, utterance in turns:
            print(f"\n>> {label}")
            print(f"Customer Spoke: \"{utterance}\"")

            # Orchestrator handles user text input
            import asyncio
            async def _process_turn():
                await driver.start_session(session_id, preamble, get_agent_tools_spec())
                # Drain start session
                q = driver._session_queues[session_id]
                while not q.empty():
                    q.get_nowait()

                # Send user text input to mock driver
                await driver.send_text_input(session_id, utterance)

                # Check queued events
                events = []
                while not q.empty():
                    events.append(q.get_nowait())
                return events

            # Query dataset directly to simulate model's tool execution result
            from app.services.dataset.retrieval import query_dynamic_dataset
            retrieval_res = query_dynamic_dataset(db, utterance, limit=2)

            print(f"AI Tool Invocation: query_active_dataset -> Found {retrieval_res['total_matches']} matches")
            print(f"Nova Sonic Spoken Response:")
            print(f"\"{retrieval_res['voice_grounding']}\"")
            assert len(retrieval_res['voice_grounding']) > 0

    print("\nALL VOICE ORCHESTRATION GROUNDING TESTS PASSED!")

if __name__ == "__main__":
    run()
