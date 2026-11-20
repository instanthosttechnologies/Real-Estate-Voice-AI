import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

pytest.importorskip("aws_sdk_bedrock_runtime", reason="aws-sdk-bedrock-runtime requires Python >= 3.12")

from app.services.voice.bedrock_streaming import BedrockNovaSonicSerializer


def test_sdk_stream_transport_instantiation():
    """Validates that BedrockSDKStreamTransport initializes cleanly with profile."""
    from app.services.voice.sdk_transport import BedrockSDKStreamTransport
    transport = BedrockSDKStreamTransport(profile_name="realestate-nova")
    assert transport.profile_name == "realestate-nova"


class MockInputStream:
    def __init__(self):
        self.sent_items = []
        self.close_called = False

    async def send(self, item):
        self.sent_items.append(item)

    async def close(self):
        self.close_called = True


def test_sdk_stream_connection_send_event():
    """Validates that BedrockSDKStreamConnection serializes events into SDK input chunks."""
    async def _run():
        from app.services.voice.sdk_transport import BedrockSDKStreamConnection
        from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk

        mock_client = MagicMock()
        mock_stream = MagicMock()
        mock_input_stream = MockInputStream()
        mock_stream.input_stream = mock_input_stream

        conn = BedrockSDKStreamConnection(client=mock_client, stream=mock_stream)

        session_start = BedrockNovaSonicSerializer.serialize_session_start(max_tokens=512)
        await conn.send_event(session_start)

        assert len(mock_input_stream.sent_items) == 1
        call_arg = mock_input_stream.sent_items[0]
        assert isinstance(call_arg, InvokeModelWithBidirectionalStreamInputChunk)
        payload_str = call_arg.value.bytes_.decode("utf-8")
        parsed_payload = json.loads(payload_str)
        assert parsed_payload["event"]["sessionStart"]["inferenceConfiguration"]["maxTokens"] == 512
        # Verify strict compaction with zero whitespace
        assert " " not in payload_str
    asyncio.run(_run())


def test_sdk_stream_connection_receive_chunks():
    """Validates that BedrockSDKStreamConnection unpacks model output chunks."""
    async def _run():
        from app.services.voice.sdk_transport import BedrockSDKStreamConnection
        from aws_sdk_bedrock_runtime.models import (
            BidirectionalOutputPayloadPart,
            InvokeModelWithBidirectionalStreamOutputChunk,
        )

        mock_client = MagicMock()
        mock_stream = MagicMock()

        sample_output = {
            "event": {
                "textOutput": {
                    "promptName": "p1",
                    "contentName": "c1",
                    "content": "Hello from Nova Sonic",
                }
            }
        }
        raw_bytes = json.dumps(sample_output).encode("utf-8")
        chunk = InvokeModelWithBidirectionalStreamOutputChunk(
            value=BidirectionalOutputPayloadPart(bytes_=raw_bytes)
        )

        async def mock_output_gen():
            yield chunk

        mock_stream.await_output = AsyncMock(return_value=({}, mock_output_gen()))

        conn = BedrockSDKStreamConnection(client=mock_client, stream=mock_stream)
        events = []
        async for evt in conn.receive_events():
            events.append(evt)

        assert len(events) == 1
        assert events[0]["event"]["textOutput"]["content"] == "Hello from Nova Sonic"
    asyncio.run(_run())


def test_sdk_stream_connection_graceful_close():
    """Validates clean teardown of both stream and client."""
    async def _run():
        from app.services.voice.sdk_transport import BedrockSDKStreamConnection

        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_stream = MagicMock()
        mock_input_stream = MockInputStream()
        mock_stream.input_stream = mock_input_stream
        mock_stream.__aexit__ = AsyncMock()

        conn = BedrockSDKStreamConnection(client=mock_client, stream=mock_stream)
        await conn.close()

        assert conn._closed is True
        assert mock_input_stream.close_called is True
        assert mock_client.close.call_count == 1
    asyncio.run(_run())
