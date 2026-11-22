import hashlib
import secrets
from hmac import compare_digest


SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived_key.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_key = encoded_hash.split("$")
        if algorithm != "scrypt" or (int(raw_n), int(raw_r), int(raw_p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt = bytes.fromhex(raw_salt)
        expected_key = bytes.fromhex(raw_key)
        if len(salt) != SALT_BYTES or len(expected_key) != SCRYPT_DKLEN:
            return False
        derived_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=SCRYPT_DKLEN,
            maxmem=SCRYPT_MAXMEM,
        )
    except (TypeError, ValueError):
        return False
    return compare_digest(derived_key, expected_key)


def new_token() -> str:
    return secrets.token_urlsafe(32)
