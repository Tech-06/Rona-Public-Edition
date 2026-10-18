"""Password hashing for the web dashboard's login (``rona web password``).

Independent stdlib copy of ``web-client/webui/auth.py``'s hash_password /
verify_password: the CLI must not import the web-client (and vice versa), so
the format -- ``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``, urlsafe base64
without padding -- is pinned by the same fixed test vector in both test
suites (cli/tests/test_webauth.py, web-client/tests/test_auth.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16
# n=2**15, r=8 needs ~32 MiB; hashlib's default memory cap is exactly that
# and rejects it, so raise it explicitly.
SCRYPT_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD_LENGTH = 4


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """``salt`` is only for the fixed test vector; production always draws a fresh one."""
    salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check; a malformed ``stored`` string is just ``False``."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False
