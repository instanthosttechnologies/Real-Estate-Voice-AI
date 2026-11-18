import logging
from typing import Optional
from app.core.config import settings
from app.services.voice.base import VoiceDriver
from app.services.voice.mock_driver import MockVoiceDriver
from app.services.voice.nova_sonic_driver import AmazonNovaSonicDriver

logger = logging.getLogger("voice_driver_factory")


def get_voice_driver(override_mock: Optional[bool] = None) -> VoiceDriver:
    """
    Returns the configured VoiceDriver instance.
    Defaults strictly to MockVoiceDriver when USE_MOCK_VOICE=True, guaranteeing
    zero cloud costs and full offline local execution capability.
    
    Safe Preflight Latch:
    Live AWS Bedrock driver requires BOTH USE_MOCK_VOICE=False AND LIVE_TEST_APPROVED=True.
    """
    use_mock = settings.USE_MOCK_VOICE if override_mock is None else override_mock

    if use_mock:
        logger.info("Initializing MockVoiceDriver (zero-cost offline mode).")
        return MockVoiceDriver(model_id=settings.BEDROCK_MODEL_ID)

    # Preflight Safe Latch: When activating live in environment, require explicit approval
    if override_mock is None and not getattr(settings, "LIVE_TEST_APPROVED", False):
        raise PermissionError(
            "Live AWS Bedrock inference is blocked: LIVE_TEST_APPROVED is False. "
            "To activate live testing, you must explicitly set LIVE_TEST_APPROVED=True and configure AWS credentials."
        )

    logger.info(
        f"Initializing AmazonNovaSonicDriver for model {settings.BEDROCK_MODEL_ID} "
        f"in region {settings.AWS_REGION} (profile: {settings.AWS_PROFILE})."
    )
    return AmazonNovaSonicDriver(
        model_id=settings.BEDROCK_MODEL_ID,
        region_name=settings.AWS_REGION,
        profile_name=settings.AWS_PROFILE,
    )
