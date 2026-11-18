import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import argon2
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import jwt

from app.core.config import settings

# -----------------------------------------------------------------------------
# AES-256-GCM Transcript Encryption Engine
# -----------------------------------------------------------------------------

def _get_encryption_key() -> bytes:
    """
    Parses and validates the 32-byte key for AES-256-GCM.
    Supports 64-character hex strings or standard raw bytes.
    """
    raw_key = settings.ENCRYPTION_MASTER_KEY.strip()
    if len(raw_key) == 64:
        try:
            key_bytes = bytes.fromhex(raw_key)
            if len(key_bytes) == 32:
                return key_bytes
        except ValueError:
            pass
    # If not 64 hex chars, derive a deterministic 32-byte key via SHA-256
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def encrypt_transcript(plaintext: str) -> str:
    """
    Encrypts a plaintext transcript using AES-256-GCM.
    Returns a URL-safe Base64-encoded string: nonce (12 bytes) + ciphertext + tag (16 bytes).
    """
    if not plaintext:
        return ""
    
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    
    # 96-bit (12-byte) nonce recommended by NIST SP 800-38D
    nonce = os.urandom(12)
    plaintext_bytes = plaintext.encode("utf-8")
    
    # encrypt automatically appends the 16-byte authentication tag to ciphertext
    ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=None)
    
    # Pack: nonce (12 bytes) + ciphertext_and_tag
    encrypted_payload = nonce + ciphertext_and_tag
    return base64.urlsafe_b64encode(encrypted_payload).decode("ascii")


def decrypt_transcript(encrypted_base64: str) -> str:
    """
    Decrypts an AES-256-GCM encrypted transcript payload.
    Raises ValueError on tampering or invalid key/payload.
    """
    if not encrypted_base64:
        return ""
    
    try:
        raw_payload = base64.urlsafe_b64decode(encrypted_base64.encode("ascii"))
    except Exception as exc:
        raise ValueError(f"Invalid Base64 ciphertext: {exc}")
    
    if len(raw_payload) < 28:  # 12 bytes nonce + 16 bytes tag minimum
        raise ValueError("Ciphertext payload is too short to be valid AES-256-GCM")
    
    nonce = raw_payload[:12]
    ciphertext_and_tag = raw_payload[12:]
    
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    
    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, associated_data=None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Decryption failed or payload tampered: {exc}")


# -----------------------------------------------------------------------------
# Password Hashing (Argon2id RFC 9106, 64MB memory cost, 3 iterations)
# -----------------------------------------------------------------------------

_password_hasher = argon2.PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=argon2.Type.ID  # Explicit Argon2id
)


def hash_password(password: str) -> str:
    """
    Hashes password using Argon2id (RFC 9106, 64 MB memory cost, 3 iterations).
    """
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain password against the Argon2id hash.
    Also provides fallback for scrypt legacy hashes if present.
    """
    if not hashed_password or not plain_password:
        return False

    if hashed_password.startswith("$argon2"):
        try:
            return _password_hasher.verify(hashed_password, plain_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # Fallback for scrypt hashes
    if hashed_password.startswith("scrypt$"):
        try:
            parts = hashed_password.split("$")
            if len(parts) != 6:
                return False
            n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
            salt = bytes.fromhex(parts[4])
            expected_dk = bytes.fromhex(parts[5])

            actual_dk = hashlib.scrypt(
                plain_password.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
                maxmem=64 * 1024 * 1024
            )
            return hmac.compare_digest(expected_dk, actual_dk)
        except Exception:
            return False

    return False


# -----------------------------------------------------------------------------
# JWT Access Tokens
# -----------------------------------------------------------------------------

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a signed JWT with expiration and subject claims.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and validates a JWT token. Raises jwt.PyJWTError on expiration or invalid signature.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# -----------------------------------------------------------------------------
# Password Policy Validator
# -----------------------------------------------------------------------------

def validate_password_strength(password: str) -> None:
    """
    Enforces production-grade password complexity rules:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        raise ValueError("Password must contain at least one special character.")


# -----------------------------------------------------------------------------
# Refresh Token Rotation & Revocation
# -----------------------------------------------------------------------------

def hash_token(raw_token: str) -> str:
    """Computes SHA-256 digest of a raw token string."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_refresh_token(db: Any, user_id: Any) -> str:
    """
    Generates a secure cryptographic refresh token, persists its SHA-256 hash,
    and returns the raw token string to the client.
    """
    from app.models.refresh_token import RefreshToken

    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    token_record = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(token_record)
    db.commit()
    db.refresh(token_record)
    return raw_token


def rotate_refresh_token(db: Any, raw_token: str) -> Tuple[Any, str]:
    """
    Rotates a refresh token:
    - Verifies token hash exists, is not expired, and is not revoked.
    - REPLAY ATTACK DETECTION: If the presented token is already revoked,
      immediately revokes all active refresh tokens for the compromised user.
    - Otherwise, marks the current token revoked and issues a fresh replacement pair.
    """
    from app.models.refresh_token import RefreshToken
    from app.models.user import User

    token_hash = hash_token(raw_token)
    token_record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if not token_record:
        raise ValueError("Invalid refresh token.")

    # Replay attack defense
    if token_record.revoked:
        # Invalidate all active sessions for this user
        db.query(RefreshToken).filter(
            RefreshToken.user_id == token_record.user_id,
            RefreshToken.revoked == False,
        ).update({"revoked": True})
        db.commit()
        raise ValueError("Revoked refresh token presented. Security alert: All active sessions invalidated.")

    now = datetime.now(timezone.utc)
    token_exp = token_record.expires_at
    if token_exp.tzinfo is None:
        token_exp = token_exp.replace(tzinfo=timezone.utc)

    if token_exp < now:
        token_record.revoked = True
        db.commit()
        raise ValueError("Refresh token has expired.")

    user = db.get(User, token_record.user_id)
    if not user or not user.is_active:
        raise ValueError("User account inactive or deleted.")

    # Mark current token revoked (single-use rotation)
    token_record.revoked = True
    db.commit()

    # Issue new refresh token
    new_raw_token = create_refresh_token(db, user.id)
    return user, new_raw_token


def revoke_refresh_token(db: Any, raw_token: str) -> bool:
    """Revokes a specific refresh token upon user logout."""
    from app.models.refresh_token import RefreshToken

    token_hash = hash_token(raw_token)
    token_record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if token_record:
        token_record.revoked = True
        db.commit()
        return True
    return False


# -----------------------------------------------------------------------------
# Rate Limiting & Brute-Force Protection
# -----------------------------------------------------------------------------

class LoginRateLimiter:
    """
    In-memory rate limiter for login brute-force mitigation:
    - Tracks consecutive failed attempts per key (email or IP).
    - Locks out after MAX_FAILED_ATTEMPTS (5) for LOCKOUT_SECONDS (15 minutes).
    - Automatically resets upon successful login.
    """
    MAX_FAILED_ATTEMPTS: int = 5
    LOCKOUT_SECONDS: int = 900  # 15 minutes

    def __init__(self):
        self._failures: Dict[str, List[float]] = {}
        self._lockouts: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_locked(self, key: str) -> Tuple[bool, int]:
        """Returns (is_locked, remaining_seconds)."""
        now = time.time()
        with self._lock:
            if key in self._lockouts:
                locked_until = self._lockouts[key]
                if now < locked_until:
                    return True, int(locked_until - now)
                else:
                    # Lock expired
                    del self._lockouts[key]
                    self._failures.pop(key, None)
            return False, 0

    def record_failure(self, key: str) -> int:
        """
        Records a failed attempt.
        Returns the number of remaining attempts before lockout.
        """
        now = time.time()
        with self._lock:
            # Clean old attempts older than lockout window
            attempts = [t for t in self._failures.get(key, []) if now - t < self.LOCKOUT_SECONDS]
            attempts.append(now)
            self._failures[key] = attempts

            if len(attempts) >= self.MAX_FAILED_ATTEMPTS:
                self._lockouts[key] = now + self.LOCKOUT_SECONDS
                return 0
            return self.MAX_FAILED_ATTEMPTS - len(attempts)

    def reset(self, key: str) -> None:
        """Clears failed attempts upon successful authentication."""
        with self._lock:
            self._failures.pop(key, None)
            self._lockouts.pop(key, None)


login_rate_limiter = LoginRateLimiter()

