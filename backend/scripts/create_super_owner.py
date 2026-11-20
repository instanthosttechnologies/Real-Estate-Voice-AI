import argparse
import getpass
import re
import sys
import uuid
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.customer import Customer
from app.models.user import User


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


def setup_super_owner(email: str = "shyamsankar0001@gmail.com", password: str = None) -> None:
    if not password:
        password = getpass.getpass(f"Enter secure password for {email}: ")
        confirm_password = getpass.getpass("Confirm password: ")
        if password != confirm_password:
            print("Error: Passwords do not match.")
            sys.exit(1)

    try:
        validate_password_complexity(password)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Convert asyncpg connection string to psycopg2 for synchronous script execution
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(sync_url)

    hashed_pw = hash_password(password)
    # Sanity check Argon2id verification
    assert verify_password(password, hashed_pw), "Argon2id hash verification failed!"

    with Session(engine) as session:
        # Check if user already exists
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

        if user:
            print(f"Updating existing user {email} to super_owner...")
            user.role = "super_owner"
            user.hashed_password = hashed_pw
            user.is_active = True
        else:
            print(f"Creating new super_owner user for {email}...")
            user = User(
                id=uuid.uuid4(),
                email=email,
                hashed_password=hashed_pw,
                role="super_owner",
                is_active=True,
            )
            session.add(user)

        session.flush()

        # Link to customer profile if exists
        cust = session.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()
        if cust:
            print(f"Linking customer profile {cust.id} (phone: {cust.phone}) to user...")
            cust.user_id = user.id
            cust.is_verified = True
        else:
            print("No matching customer record found to link.")

        session.commit()
        print(f"[SUCCESS] Super Owner account configured for {email}!")
        print(f"  User ID: {user.id}")
        print(f"  Role: {user.role}")
        print(f"  Authorized Dashboards: /admin and /super-owner")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configure Super Owner Account")
    parser.add_argument("--email", default="shyamsankar0001@gmail.com", help="Email address")
    parser.add_argument("--password", default=None, help="Optional direct password (or prompts if omitted)")
    args = parser.parse_args()

    setup_super_owner(email=args.email, password=args.password)
