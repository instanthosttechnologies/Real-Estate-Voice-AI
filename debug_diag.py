import sys
sys.path.insert(0, "backend")
import asyncio
from tests.test_voice_driver import SimulatedHttp2ClientConnection
from app.services.voice.bedrock_streaming import _CRTBedrockStreamConnection

async def _run():
    print("1. Creating sim_conn...")
    sim_conn = SimulatedHttp2ClientConnection()
    print("2. Creating _CRTBedrockStreamConnection...")
    conn = _CRTBedrockStreamConnection(
        endpoint="bedrock-runtime.us-east-1.amazonaws.com",
        path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
        region="us-east-1",
        access_key_id="AKIA_MOCK_KEY",
        secret_access_key="MOCK_SECRET",
        connection_factory=lambda: asyncio.sleep(0.01, result=sim_conn),
    )
    print("3. Calling conn.connect()...")
    await conn.connect()
    print("4. Connected!")
    print("5. Sending event...")
    evt = {"event": {"audioInput": {"promptName": "p1", "contentName": "c1", "content": "AQID"}}}
    await conn.send_event(evt)
    print("6. Event sent!")
    print("7. Closing conn...")
    await conn.close()
    print("8. Closed!")

if __name__ == "__main__":
    asyncio.run(_run())
    print("ALL DONE!")
