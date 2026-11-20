import getpass
import hashlib
import hmac
import os
import re
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.user import User
from app.services.otp_delivery import send_email_otp


def validate_password_complexity(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one special character.")


def main():
    email = "shyamsankar0001@gmail.com"
    print("=" * 70)
    print("  BRAIN MAGIC REAL ESTATE VOICE AI — SECURE SUPER OWNER SETUP")
    print("=" * 70)
    print(f"Target Account Email: {email}")
    print("Authorized Role     : super_owner (Platform Super Owner & Administrator)\n")

    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(sync_url)

    # -------------------------------------------------------------------------
    # STEP 1: Recheck users table
    # -------------------------------------------------------------------------
    print("[1/5] Checking existing database accounts...")
    with Session(engine) as session:
        existing_user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing_user:
            print(f"[ERROR] An account for {email} already exists in the users table (Role: {existing_user.role}).")
            print("Aborting to prevent duplicate account creation.")
            sys.exit(1)
        print("      OK: No existing account found in users table for this email.")

    # -------------------------------------------------------------------------
    # STEP 2: Email Ownership Verification
    # -------------------------------------------------------------------------
    print("\n[2/5] Initiating Email Ownership Verification...")
    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
    
    # Compute HMAC of OTP
    hmac_secret = os.getenv("OTP_HMAC_SECRET", "dev-secret-key-replace-in-production-min32chars").encode("utf-8")
    expected_hmac = hmac.new(hmac_secret, otp_code.encode("utf-8"), hashlib.sha256).hexdigest()

    print(f"      Sending 6-digit verification code to {email} via Gmail SMTP...")
    try:
        send_email_otp(email, otp_code)
        print("      Verification email dispatched successfully!")
    except Exception as exc:
        print(f"[ERROR] Failed to dispatch verification email: {exc}")
        sys.exit(1)

    print(f"\nPlease check your inbox at {email}.")
    entered_otp = input("Enter the 6-digit verification code: ").strip()

    entered_hmac = hmac.new(hmac_secret, entered_otp.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(entered_hmac, expected_hmac):
        print("\n[ERROR] Invalid verification code. Email ownership could not be verified.")
        sys.exit(1)

    print("      Verification successful: Email address ownership confirmed.")

    # -------------------------------------------------------------------------
    # STEP 3: Secure Password Setup
    # -------------------------------------------------------------------------
    print("\n[3/5] Secure Password Entry")
    print("Password rules: Min 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special character.")
    while True:
        pw1 = getpass.getpass("Enter new password for Super Owner: ")
        pw2 = getpass.getpass("Confirm new password: ")
        if pw1 != pw2:
            print("Passwords do not match. Please try again.\n")
            continue
        try:
            validate_password_complexity(pw1)
            break
        except ValueError as e:
            print(f"Password complexity error: {e}. Please try again.\n")

    print("      Hashing password with Argon2id (RFC 9106, 64MB memory cost, 3 iterations)...")
    hashed_password = hash_password(pw1)
    assert verify_password(pw1, hashed_password), "Argon2id self-test verification failed!"
    print("      Password hash generated and verified successfully.")

    # -------------------------------------------------------------------------
    # STEP 4: Atomic Database Transaction
    # -------------------------------------------------------------------------
    print("\n[4/5] Creating Super Owner Account in PostgreSQL (Atomic Transaction)...")
    with Session(engine) as session:
        try:
            # Recheck inside transaction
            user_check = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user_check:
                raise RuntimeError("Race condition detected: User was created concurrently.")

            user_id = uuid.uuid4()
            new_user = User(
                id=user_id,
                email=email,
                hashed_password=hashed_password,
                role="super_owner",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(new_user)
            session.flush()

            # Check and link customer profile if exists with matching email
            cust = session.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()
            if cust:
                print(f"      Linking verified customer record {cust.id} (phone: {cust.phone}) to user...")
                cust.user_id = user_id
                cust.is_verified = True
                cust.updated_at = datetime.now(timezone.utc)

            # Record privileged account creation in audit log
            audit = AuditLog(
                user_id=user_id,
                user_role="super_owner",
                action="SUPER_OWNER_ACCOUNT_BOOTSTRAPPED",
                resource_type="user",
                resource_id=str(user_id),
                meta_info={
                    "email": email,
                    "auth_method": "email_otp_verified",
                    "role_granted": "super_owner",
                },
                timestamp=datetime.now(timezone.utc),
            )
            session.add(audit)

            session.commit()
            print("      Transaction committed successfully! Super Owner record created.")
        except Exception as exc:
            session.rollback()
            print(f"[FATAL] Transaction failed and was rolled back: {exc}")
            sys.exit(1)

    # -------------------------------------------------------------------------
    # STEP 5: Authentication & Dashboard Access Verification
    # -------------------------------------------------------------------------
    print("\n[5/5] Verifying Authentication & Role-Based Access...")
    # Test login token creation
    token = create_access_token(
        data={"sub": str(user_id), "role": "super_owner", "email": email}
    )
    claims = decode_access_token(token)
    assert claims.get("role") == "super_owner", "Token role must be super_owner"
    assert claims.get("email") == email, "Token email must match"

    print("      JWT Token Issued & Decoded Successfully.")
    print("      Role Verified: super_owner")
    print("\n" + "=" * 70)
    print("  CONFIGURATION COMPLETE")
    print("=" * 70)
    print(f"Account Email: {email}")
    print("Account Role : super_owner")
    print("Status       : Active & Verified")
    print("\nAuthorized Dashboard Access:")
    print("  - Admin Dashboard      : http://localhost:3000/admin")
    print("  - Super Owner Dashboard: http://localhost:3000/super-owner")
    print("  - Voice Customer Portal: http://localhost:3000/customer")
    print("  - Unified Login Page   : http://localhost:3000/login (Select 'Admin Login')")
    print("=" * 70)


if __name__ == "__main__":
    main()
