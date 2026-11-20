"""AWS-supported bidirectional streaming transport for Nova Sonic.

Place next to bedrock_streaming.py and use BedrockSDKStreamTransport as
AmazonNovaSonicDriver's default transport. No AWS calls on import.

Requires: pip install "aws-sdk-bedrock-runtime[awscrt]"
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from app.services.voice.bedrock_streaming import BedrockStreamConnection, BedrockStreamTransport

logger = logging.getLogger(__name__)


class BedrockSDKStreamConnection(BedrockStreamConnection):
    def __init__(self, client: Any, stream: Any):
        self._client = client
        self._stream = stream
        self._closed = False
        self._send_lock = asyncio.Lock()

    async def send_event(self, event_dict: Dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("Nova Sonic SDK stream is closed")
        from aws_sdk_bedrock_runtime.models import (
            BidirectionalInputPayloadPart,
            InvokeModelWithBidirectionalStreamInputChunk,
        )
        # The SDK, not application code, handles HTTP/2 framing and signing.
        payload = json.dumps(event_dict, separators=(",", ":")).encode("utf-8")
        sdk_event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=payload)
        )
        async with self._send_lock:
            await self._stream.input_stream.send(sdk_event)

    async def receive_events(self) -> AsyncIterator[Dict[str, Any]]:
        from aws_sdk_bedrock_runtime.models import (
            InvokeModelWithBidirectionalStreamOutputChunk,
            InvokeModelWithBidirectionalStreamOutputValidationException,
        )
        try:
            _metadata, output_stream = await self._stream.await_output()
            if output_stream is None:
                raise RuntimeError("Bedrock returned no bidirectional output stream")
            async for response in output_stream:
                if self._closed:
                    return
                if isinstance(response, InvokeModelWithBidirectionalStreamOutputChunk):
                    payload = response.value.bytes_
                    if payload:
                        yield json.loads(payload.decode("utf-8"))
                else:
                    # SDK represents service errors as typed event union variants.
                    tag = type(response).__name__
                    value = getattr(response, "value", None)
                    message = getattr(value, "message", None) or tag
                    if isinstance(response, InvokeModelWithBidirectionalStreamOutputValidationException):
                        error_type = "validationException"
                    else:
                        error_type = "modelStreamErrorException"
                    yield {"event": {error_type: {"message": str(message), "sdk_error_type": tag}}}
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Nova Sonic SDK response stream failed")
            yield {"event": {"modelStreamErrorException": {"message": str(exc)}}}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._stream.input_stream.close()
        except Exception:
            logger.debug("Input stream already closed", exc_info=True)
        try:
            await self._stream.__aexit__(None, None, None)
        finally:
            await self._client.close()


class BedrockSDKStreamTransport(BedrockStreamTransport):
    """Use the AWS-generated Bedrock client to own SigV4 + EventStream framing."""

    def __init__(self, profile_name: Optional[str] = None):
        self.profile_name = profile_name

    async def open_stream(
        self, model_id: str, region: str, session_id: str
    ) -> BedrockStreamConnection:
        from aws_sdk_bedrock_runtime.client import AsyncBedrockRuntimeClient
        from aws_sdk_bedrock_runtime.config import AsyncBedrockRuntimeConfig
        from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamOperationInput
        from smithy_http.aio.crt import AWSCRTHTTPClient

        config = await AsyncBedrockRuntimeConfig.resolve(
            profile=self.profile_name,
            region=region,
            transport=AWSCRTHTTPClient(),
        )
        client = AsyncBedrockRuntimeClient(config=config)
        try:
            stream = await client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=model_id)
            )
            await stream.__aenter__()
            logger.info("Nova Sonic SDK duplex session opened: %s", session_id)
            return BedrockSDKStreamConnection(client, stream)
        except Exception:
            await client.close()
            raise
