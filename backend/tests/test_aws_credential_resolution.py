import asyncio
import os
import pytest
from unittest.mock import MagicMock, patch
import botocore.session
from botocore.credentials import Credentials, ReadOnlyCredentials

from app.core.config import settings
from app.services.voice.bedrock_streaming import (
    BedrockCRTStreamTransport,
    _CRTBedrockStreamConnection,
    resolve_aws_credentials,
)
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver


def test_named_profile_resolution_offline():
    """Verify credentials resolve via named botocore session profile without network."""
    mock_b_session = MagicMock()
    mock_creds = ReadOnlyCredentials("AKIAMOCKPROFILE1234", "MOCKSECRETKEYPROFILE1234", None)
    mock_b_session.get_credentials.return_value = mock_creds

    resolved = resolve_aws_credentials(
        profile_name="realestate-nova",
        botocore_session=mock_b_session,
    )
    assert resolved is not None
    assert resolved.access_key == "AKIAMOCKPROFILE1234"
    assert resolved.secret_key == "MOCKSECRETKEYPROFILE1234"
    assert resolved.token is None


def test_actual_realestate_nova_profile_if_configured():
    """Verify that if realestate-nova profile exists in ~/.aws/credentials, it resolves cleanly."""
    session = botocore.session.get_session()
    if "realestate-nova" in session.available_profiles:
        resolved = resolve_aws_credentials(profile_name="realestate-nova")
        assert resolved is not None
        assert bool(resolved.access_key) is True
        assert bool(resolved.secret_key) is True


def test_missing_credentials_rejection():
    """Verify missing credentials return None and open_stream raises RuntimeError."""
    mock_b_session = MagicMock()
    mock_b_session.get_credentials.return_value = None

    with patch.object(settings, "AWS_ACCESS_KEY_ID", None):
        with patch.object(settings, "AWS_SECRET_ACCESS_KEY", None):
            with patch.object(settings, "AWS_PROFILE", None):
                with patch.dict(os.environ, {}, clear=True):
                    resolved = resolve_aws_credentials(botocore_session=mock_b_session)
                    assert resolved is None

                    transport = BedrockCRTStreamTransport(
                        profile_name=None,
                        botocore_session=mock_b_session,
                    )
                    assert transport.get_credentials() is None

                    with pytest.raises(RuntimeError) as exc_info:
                        asyncio.run(
                            transport.open_stream(
                                model_id="amazon.nova-2-5-sonic",
                                region="ap-northeast-1",
                                session_id="test_missing_creds",
                            )
                        )
                    assert "AWS credentials not configured" in str(exc_info.value)


def test_temporary_session_tokens_and_sigv4_signing():
    """Verify temporary STS session tokens are included in SigV4 signing headers."""
    temp_creds = ReadOnlyCredentials("ASIATESTTEMPKEY123", "MOCKTEMPSECRETKEY123", "STS_SESSION_TOKEN_ABC123")

    conn = _CRTBedrockStreamConnection(
        endpoint="bedrock-runtime.ap-northeast-1.amazonaws.com",
        path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
        region="ap-northeast-1",
        credentials=temp_creds,
    )

    signed_req = conn._create_signed_request()
    assert signed_req is not None
    assert signed_req.method == "POST"
    assert signed_req.path == "/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream"

    # Verify signed headers
    headers_dict = dict(signed_req.headers)
    assert headers_dict["Host"] == "bedrock-runtime.ap-northeast-1.amazonaws.com"
    assert headers_dict["Content-Type"] == "application/vnd.amazon.eventstream"
    assert headers_dict["Accept"] == "application/vnd.amazon.eventstream"
    assert headers_dict["X-Amz-Security-Token"] == "STS_SESSION_TOKEN_ABC123"
    assert "Authorization" in headers_dict
    assert "AWS4-HMAC-SHA256" in headers_dict["Authorization"]
    assert "bedrock/aws4_request" in headers_dict["Authorization"]
    assert "ap-northeast-1" in headers_dict["Authorization"]


def test_backward_compatibility_explicit_keys():
    """Verify explicit access keys override SDK provider chain and sign properly."""
    explicit_access = "AKIAEXPLICITOVERRIDE"
    explicit_secret = "EXPLICITSECRET1234567890"

    transport = BedrockCRTStreamTransport(
        access_key_id=explicit_access,
        secret_access_key=explicit_secret,
        session_token="EXPLICIT_TOKEN",
    )
    resolved = transport.get_credentials()
    assert resolved is not None
    assert resolved.access_key == explicit_access
    assert resolved.secret_key == explicit_secret
    assert resolved.token == "EXPLICIT_TOKEN"

    conn = _CRTBedrockStreamConnection(
        endpoint="bedrock-runtime.ap-northeast-1.amazonaws.com",
        path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
        region="ap-northeast-1",
        access_key_id=explicit_access,
        secret_access_key=explicit_secret,
        session_token="EXPLICIT_TOKEN",
    )
    signed_req = conn._create_signed_request()
    headers_dict = dict(signed_req.headers)
    assert headers_dict["X-Amz-Security-Token"] == "EXPLICIT_TOKEN"
    assert explicit_access in headers_dict["Authorization"]


def test_refreshable_credentials_resolution():
    """Verify that credentials resolver fetches refreshed credentials at signing time."""
    call_count = 0

    def mock_resolver():
        nonlocal call_count
        call_count += 1
        return ReadOnlyCredentials(
            f"AKIAREFRESHKEY_{call_count}",
            f"MOCKSECRET_{call_count}",
            f"TOKEN_{call_count}",
        )

    conn = _CRTBedrockStreamConnection(
        endpoint="bedrock-runtime.ap-northeast-1.amazonaws.com",
        path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
        region="ap-northeast-1",
        credentials_resolver=mock_resolver,
    )

    # First sign
    req1 = conn._create_signed_request()
    h1 = dict(req1.headers)
    assert "AKIAREFRESHKEY_1" in h1["Authorization"]
    assert h1["X-Amz-Security-Token"] == "TOKEN_1"

    # Second sign (refreshed snapshot)
    req2 = conn._create_signed_request()
    h2 = dict(req2.headers)
    assert "AKIAREFRESHKEY_2" in h2["Authorization"]
    assert h2["X-Amz-Security-Token"] == "TOKEN_2"


def test_driver_inherits_configured_profile():
    """Verify AmazonNovaSonicDriver initializes transport with configured profile."""
    with patch.object(settings, "AWS_PROFILE", "realestate-nova"):
        with patch.object(settings, "AWS_REGION", "ap-northeast-1"):
            driver = AmazonNovaSonicDriver()
            assert driver._profile_name == "realestate-nova"
            assert driver._region_name == "ap-northeast-1"
            assert isinstance(driver._transport, BedrockCRTStreamTransport)
            assert driver._transport.profile_name == "realestate-nova"


def test_secrets_never_logged_or_exposed_in_repr():
    """Verify that repr, str, and logging do not leak secret access keys."""
    secret = "SUPER_SECRET_AWS_KEY_DO_NOT_LEAK"
    token = "SUPER_SECRET_SESSION_TOKEN"
    transport = BedrockCRTStreamTransport(
        access_key_id="AKIAEXPOSURECHECK",
        secret_access_key=secret,
        session_token=token,
    )
    transport_repr = repr(transport)
    assert secret not in transport_repr
    assert token not in transport_repr

    conn = _CRTBedrockStreamConnection(
        endpoint="bedrock-runtime.ap-northeast-1.amazonaws.com",
        path="/model/amazon.nova-2-5-sonic/invoke-with-bidirectional-stream",
        region="ap-northeast-1",
        access_key_id="AKIAEXPOSURECHECK",
        secret_access_key=secret,
        session_token=token,
    )
    conn_repr = repr(conn)
    assert secret not in conn_repr
    assert token not in conn_repr
