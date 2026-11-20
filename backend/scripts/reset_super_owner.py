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
    login_rate_limiter,
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
    print("  BRAIN MAGIC REAL ESTATE VOICE AI — RESET SUPER OWNER LOGIN")
    print("=" * 70)
    print(f"Target Account: {email}")
    print("Target Role   : super_owner\n")

    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(sync_url)

    # -------------------------------------------------------------------------
    # STEP 1: Inspect Existing Account State
    # -------------------------------------------------------------------------
    print("[1/4] Inspecting existing account state in PostgreSQL...")
    with Session(engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        cust = session.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()

        if user:
            print(f"      Found User record: ID={user.id}, Role={user.role}, Active={user.is_active}")
        else:
            print(f"      Notice: No User record currently in 'users' table for {email}.")
            print("      (Failed login attempts on this uncreated account triggered the 15-minute lock).")

        if cust:
            print(f"      Found Customer record: ID={cust.id}, Name={cust.full_name}, Phone={cust.phone}")
            print(f"      Customer Verified: {cust.is_verified}, OTP Attempts: {cust.otp_attempts}, Locked Until: {cust.otp_locked_until}")
        else:
            print("      No customer profile found.")

    # -------------------------------------------------------------------------
    # STEP 2: Verify Email Address Ownership via OTP
    # -------------------------------------------------------------------------
    print("\n[2/4] Verifying Email Ownership...")
    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
    
    hmac_secret = os.getenv("OTP_HMAC_SECRET", "dev-secret-key-replace-in-production-min32chars").encode("utf-8")
    expected_hmac = hmac.new(hmac_secret, otp_code.encode("utf-8"), hashlib.sha256).hexdigest()

    print(f"      Dispatching 6-digit verification code to {email}...")
    try:
        send_email_otp(email, otp_code)
        print("      Verification code sent successfully via SMTP!")
    except Exception as exc:
        print(f"[ERROR] Failed to dispatch verification email: {exc}")
        sys.exit(1)

    print(f"\nPlease check your inbox at {email}.")
    entered_otp = input("Enter the 6-digit verification code: ").strip()

    entered_hmac = hmac.new(hmac_secret, entered_otp.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(entered_hmac, expected_hmac):
        print("\n[ERROR] Invalid verification code. Ownership not verified. Aborting.")
        sys.exit(1)

    print("      Verification successful: Email ownership confirmed.")

    # -------------------------------------------------------------------------
    # STEP 3: Secure Password Reset & Lockout Clearance
    # -------------------------------------------------------------------------
    print("\n[3/4] Enter New Password")
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

    print("      Executing database transaction...")
    with Session(engine) as session:
        try:
            user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            user_id = user.id if user else uuid.uuid4()

            if user:
                print(f"      Updating password hash for existing user {email}...")
                user.hashed_password = hashed_password
                user.role = "super_owner"
                user.is_active = True
                user.updated_at = datetime.now(timezone.utc)
            else:
                print(f"      Creating new super_owner account for {email}...")
                user = User(
                    id=user_id,
                    email=email,
                    hashed_password=hashed_password,
                    role="super_owner",
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(user)

            session.flush()

            # Link and reset customer record
            cust = session.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()
            if cust:
                print(f"      Linking customer record {cust.id} and clearing any customer lockout...")
                cust.user_id = user.id
                cust.is_verified = True
                cust.otp_attempts = 0
                cust.otp_locked_until = None
                cust.updated_at = datetime.now(timezone.utc)

            # Record audit log
            audit = AuditLog(
                user_id=user.id,
                user_role="super_owner",
                action="SUPER_OWNER_PASSWORD_RESET_SUCCESS",
                resource_type="user",
                resource_id=str(user.id),
                meta_info={
                    "email": email,
                    "auth_verified": "email_otp",
                    "lockout_cleared": True,
                },
                timestamp=datetime.now(timezone.utc),
            )
            session.add(audit)

            session.commit()
            print("      Database transaction committed successfully!")
        except Exception as exc:
            session.rollback()
            print(f"[FATAL] Transaction failed and was rolled back: {exc}")
            sys.exit(1)

    # Reset in-memory rate limiters for this email across all common client IP formats
    for client_ip in ["127.0.0.1", "localhost", "::1", "unknown"]:
        login_rate_limiter.reset(f"{email}:{client_ip}")
    print("      In-memory login rate-limiters cleared.")

    # -------------------------------------------------------------------------
    # STEP 4: Verify Login & Dashboard Access Permissions
    # -------------------------------------------------------------------------
    print("\n[4/4] Verifying Authentication & Access...")
    # Verify hash check
    assert verify_password(pw1, hashed_password) is True, "Password verification check failed."
    print("      Argon2id Hash Verification: PASSED")

    # Generate token
    token = create_access_token(data={"sub": str(user_id), "role": "super_owner", "email": email})
    claims = decode_access_token(token)
    assert claims.get("role") == "super_owner", "Role mismatch in token"
    print("      JWT Token Issue & Claims Check: PASSED (role='super_owner')")

    print("\n" + "=" * 70)
    print("  SUPER OWNER ACCOUNT READY & UNLOCKED")
    print("=" * 70)
    print(f"Email          : {email}")
    print("Role           : super_owner")
    print("Account Status : Active (Lockout Cleared)")
    print("\nAuthorized Dashboard URLs:")
    print("  1. Unified Login Page  : http://localhost:3000/login (Select 'Admin Login')")
    print("  2. Super Owner Console : http://localhost:3000/super-owner")
    print("  3. Admin Dashboard     : http://localhost:3000/admin")
    print("  4. Customer Voice Portal: http://localhost:3000/customer")
    print("=" * 70)


if __name__ == "__main__":
    main()
