"""
Secure OTP delivery service for Real Estate Agentic Voice AI.

Supported channels:
    1. Email through SMTP (TLS)
    2. SMS through Twilio Messaging API

Important:
    - Never return OTP values in public API responses.
    - Never log OTP values or provider credentials.
    - Missing provider configuration causes delivery to fail.
    - OTP generation, expiry, hashing, rate limiting, and
      verification are handled separately.
"""

import base64
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

OTPChannel = Literal["email", "sms"]

# Load the backend .env file safely.
# Existing process environment values take priority.
BACKEND_DIR = Path(__file__).resolve().parents[2]

load_dotenv(
    dotenv_path=BACKEND_DIR / ".env",
    override=False,
)


class OTPDeliveryError(Exception):
    """Raised when an OTP cannot be delivered safely."""


def _required_env(name: str) -> str:
    """
    Read a mandatory environment variable without exposing
    its value in an error message.
    """
    value = os.getenv(name, "").strip()

    if not value:
        raise OTPDeliveryError(f"OTP delivery is not configured: {name} is missing.")

    return value


def _validate_otp(otp: str) -> None:
    """
    Accept only a six-digit verification code.
    """
    if not isinstance(otp, str):
        raise ValueError("OTP must be a string.")

    if not re.fullmatch(r"[0-9]{6}", otp):
        raise ValueError("OTP must contain exactly six digits.")


def _validate_email(email: str) -> str:
    """
    Basic email format and header-injection validation.

    The onboarding schema should perform full email
    validation before this service is called.
    """
    if not isinstance(email, str):
        raise OTPDeliveryError("Invalid email destination.")

    email = email.strip()

    if (
        "\r" in email
        or "\n" in email
        or len(email) > 254
        or not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email)
    ):
        raise OTPDeliveryError("Invalid email destination.")

    return email


def _validate_phone(phone: str) -> str:
    """
    Require E.164 international phone format.

    Example:
        +919876543210
    """
    if not isinstance(phone, str):
        raise OTPDeliveryError("Invalid SMS destination.")

    phone = phone.strip()

    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise OTPDeliveryError("SMS phone number must use E.164 format.")

    return phone


# ============================================================
# EMAIL OTP DELIVERY
# ============================================================


def send_email_otp(
    email: str,
    otp: str,
) -> None:
    """
    Deliver OTP to the customer's email address.

    Supported secure SMTP configurations:
        Port 465: SSL/TLS
        Port 587: STARTTLS

    Credentials must be provided through environment
    variables and must not be hardcoded.
    """

    destination = _validate_email(email)
    _validate_otp(otp)

    smtp_host = _required_env("OTP_SMTP_HOST")
    smtp_user = _required_env("OTP_SMTP_USER")
    smtp_password = _required_env("OTP_SMTP_PASSWORD")
    from_email = _validate_email(_required_env("OTP_SMTP_FROM_EMAIL"))

    try:
        smtp_port = int(os.getenv("OTP_SMTP_PORT", "587"))
    except ValueError as exc:
        raise OTPDeliveryError("Invalid SMTP port configuration.") from exc

    if smtp_port not in (465, 587):
        raise OTPDeliveryError("Use SMTP port 465 or 587 with TLS.")

    message = EmailMessage()

    message["Subject"] = "Your Real Estate AI Verification Code"
    message["From"] = from_email
    message["To"] = destination

    message.set_content(
        "Hello,\n\n"
        "Your Real Estate AI verification code is:\n\n"
        f"{otp}\n\n"
        "This code expires in 10 minutes.\n\n"
        "Do not share this code with anyone.\n"
        "If you did not request verification, "
        "you can ignore this email.\n\n"
        "Real Estate AI Team"
    )

    context = ssl.create_default_context()

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(
                smtp_host,
                smtp_port,
                timeout=15,
                context=context,
            ) as server:
                server.login(
                    smtp_user,
                    smtp_password,
                )

                server.send_message(message)

        else:
            with smtplib.SMTP(
                smtp_host,
                smtp_port,
                timeout=15,
            ) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()

                server.login(
                    smtp_user,
                    smtp_password,
                )

                server.send_message(message)

    except (
        smtplib.SMTPException,
        OSError,
        ssl.SSLError,
    ) as exc:
        raise OTPDeliveryError("Email OTP delivery failed.") from exc


# ============================================================
# SMS OTP DELIVERY
# ============================================================


def send_sms_otp(
    phone: str,
    otp: str,
) -> None:
    """
    Deliver OTP using Twilio Programmable Messaging.

    Required environment variables:
        TWILIO_ACCOUNT_SID
        TWILIO_AUTH_TOKEN
        TWILIO_FROM_NUMBER

    Uses the official Twilio Messages REST endpoint.
    """

    destination = _validate_phone(phone)
    _validate_otp(otp)

    account_sid = _required_env("TWILIO_ACCOUNT_SID")

    auth_token = _required_env("TWILIO_AUTH_TOKEN")

    from_number = _required_env("TWILIO_FROM_NUMBER")

    if not re.fullmatch(
        r"AC[0-9a-fA-F]{32}",
        account_sid,
    ):
        raise OTPDeliveryError("Invalid Twilio Account SID configuration.")

    sms_body = (
        "Your Real Estate AI verification code is "
        f"{otp}. Valid for 10 minutes. "
        "Do not share this code."
    )

    api_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    request_data = urlencode(
        {
            "To": destination,
            "From": from_number,
            "Body": sms_body,
        }
    ).encode("utf-8")

    credentials = (f"{account_sid}:{auth_token}").encode()

    encoded_credentials = base64.b64encode(credentials).decode("ascii")

    request = Request(
        url=api_url,
        data=request_data,
        headers={
            "Authorization": (f"Basic {encoded_credentials}"),
            "Content-Type": ("application/x-www-form-urlencoded"),
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=15,
            context=ssl.create_default_context(),
        ) as response:
            status_code = response.status

            if status_code not in (200, 201):
                raise OTPDeliveryError("SMS provider rejected the request.")

    except (HTTPError, URLError, OSError) as exc:
        raise OTPDeliveryError("SMS OTP delivery failed.") from exc


# ============================================================
# UNIFIED OTP DELIVERY
# ============================================================


def send_otp(
    channel: OTPChannel,
    destination: str,
    otp: str,
) -> None:
    """
    Send an OTP using the chosen delivery channel.

    Example:

        send_otp(
            channel="email",
            destination="customer@example.com",
            otp="123456",
        )

        send_otp(
            channel="sms",
            destination="+919876543210",
            otp="123456",
        )

    Returns:
        None on successful provider acceptance.

    Raises:
        OTPDeliveryError on delivery failure.

    This function must never return the OTP value.
    """

    if os.getenv("MOCK_OTP_DELIVERY", "").lower() in ("true", "1", "yes"):
        current_env = os.getenv("ENVIRONMENT", "").strip().lower()
        if current_env == "production":
            raise OTPDeliveryError(
                "Security violation: Mock OTP delivery is strictly prohibited in production environment."
            )
        mock_file = os.getenv("MOCK_OTP_FILE")
        if mock_file:
            Path(mock_file).parent.mkdir(parents=True, exist_ok=True)
            with open(mock_file, "w", encoding="utf-8") as f:
                f.write(otp)
        return

    if channel == "email":
        send_email_otp(
            email=destination,
            otp=otp,
        )

    elif channel == "sms":
        send_sms_otp(
            phone=destination,
            otp=otp,
        )

    else:
        raise OTPDeliveryError("Unsupported OTP delivery channel.")
