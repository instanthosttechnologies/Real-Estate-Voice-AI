import pytest
import time
from datetime import timedelta
import jwt

from app.core.security import (
    encrypt_transcript,
    decrypt_transcript,
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)
from app.core.roles import UserRole, has_permission


def test_aes_256_gcm_transcript_encryption():
    plaintext = "Customer asked for 3BHK in downtown with $1.2M budget."
    encrypted = encrypt_transcript(plaintext)
    
    assert encrypted != plaintext
    assert isinstance(encrypted, str)
    
    # Decrypt and verify
    decrypted = decrypt_transcript(encrypted)
    assert decrypted == plaintext


def test_aes_256_gcm_randomized_nonces():
    plaintext = "Sensitive conversation snippet"
    enc1 = encrypt_transcript(plaintext)
    enc2 = encrypt_transcript(plaintext)
    
    # Distinct nonces should ensure distinct ciphertext even for identical plaintext
    assert enc1 != enc2
    assert decrypt_transcript(enc1) == plaintext
    assert decrypt_transcript(enc2) == plaintext


def test_aes_256_gcm_tamper_detection():
    plaintext = "Private audio transcript"
    encrypted = encrypt_transcript(plaintext)
    
    # Tamper with the base64 ciphertext
    tampered = encrypted[:-4] + "AAAA"
    with pytest.raises(ValueError):
        decrypt_transcript(tampered)


def test_password_hashing_and_verification():
    raw_pass = "SuperSecurePassword#2026"
    hashed = hash_password(raw_pass)
    
    assert hashed != raw_pass
    assert hashed.startswith("$argon2id$")
    
    # Correct password succeeds
    assert verify_password(raw_pass, hashed) is True
    
    # Wrong password fails
    assert verify_password("WrongPassword#2026", hashed) is False


def test_jwt_access_token_lifecycle():
    payload = {"sub": "user-1234-uuid", "role": "admin", "email": "admin@realtor.com"}
    token = create_access_token(payload, expires_delta=timedelta(minutes=5))
    
    decoded = decode_access_token(token)
    assert decoded["sub"] == "user-1234-uuid"
    assert decoded["role"] == "admin"
    assert decoded["email"] == "admin@realtor.com"
    assert "exp" in decoded


def test_jwt_tamper_fails():
    token = create_access_token({"sub": "user-1"}, expires_delta=timedelta(minutes=5))
    tampered = token[:-4] + "xxxx"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)


def test_role_permission_boundaries():
    # Customer
    assert has_permission(UserRole.CUSTOMER, "voice:interact") is True
    assert has_permission(UserRole.CUSTOMER, "conversations:read_priority") is False
    assert has_permission(UserRole.CUSTOMER, "conversations:read_transcript") is False

    # Admin: CANNOT read private transcripts or audio
    assert has_permission(UserRole.ADMIN, "conversations:read_priority") is True
    assert has_permission(UserRole.ADMIN, "customers:read_all") is True
    assert has_permission(UserRole.ADMIN, "conversations:read_transcript") is False
    assert has_permission(UserRole.ADMIN, "conversations:read_audio") is False

    # Super Owner: CAN read private transcripts and audio
    assert has_permission(UserRole.SUPER_OWNER, "conversations:read_priority") is True
    assert has_permission(UserRole.SUPER_OWNER, "conversations:read_transcript") is True
    assert has_permission(UserRole.SUPER_OWNER, "conversations:read_audio") is True
    assert has_permission(UserRole.SUPER_OWNER, "ingestion:manage") is True
