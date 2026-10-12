"""Print a bcrypt hash for QUAY_ADMIN_PASSWORD.

Uses system libcrypt so Controller execution environments do not need the
bcrypt or passlib Python packages. Quay stores this value in ``password_hash``.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys


def _hash_with_stdlib_crypt(password: str) -> str | None:
    """Use stdlib crypt when present (removed in Python 3.13)."""
    try:
        import crypt
    except ImportError:
        return None
    hashed = crypt.crypt(password, crypt.METHOD_BLOWFISH)
    if not hashed:
        raise RuntimeError("crypt.crypt returned empty hash")
    return hashed


def _hash_with_libcrypt(password: str, rounds: int = 12) -> str:
    """Call libxcrypt via ctypes. No bcrypt Python package required."""
    lib = None
    candidates = []
    found = ctypes.util.find_library("crypt")
    if found:
        candidates.append(found)
    candidates.extend(("libcrypt.so.2", "libcrypt.so.1", "libcrypt.so"))
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            lib = ctypes.CDLL(candidate, use_errno=True)
            break
        except OSError as exc:
            last_error = exc
    if lib is None:
        raise RuntimeError("libcrypt is not available") from last_error
    if not hasattr(lib, "crypt_gensalt") or not hasattr(lib, "crypt"):
        raise RuntimeError("libcrypt lacks crypt_gensalt/crypt")

    lib.crypt_gensalt.argtypes = [
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    lib.crypt_gensalt.restype = ctypes.c_char_p
    lib.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.crypt.restype = ctypes.c_char_p

    salt = lib.crypt_gensalt(b"$2b$", rounds, None, 0)
    if not salt:
        raise RuntimeError("libcrypt crypt_gensalt failed")
    hashed = lib.crypt(password.encode("utf-8"), salt)
    if not hashed:
        raise RuntimeError("libcrypt crypt failed")
    return hashed.decode("ascii")


def hash_password(password: str) -> str:
    """Return a Quay bcrypt hash ($2a$/$2b$/$2y$)."""
    hashed = _hash_with_stdlib_crypt(password)
    if hashed is None:
        try:
            hashed = _hash_with_libcrypt(password)
        except RuntimeError:
            try:
                import bcrypt
            except ImportError as exc:
                raise RuntimeError(
                    "Cannot hash the Quay admin password: need libxcrypt "
                    "or an installed bcrypt Python package"
                ) from exc
            hashed = bcrypt.hashpw(
                password.encode("utf-8"),
                bcrypt.gensalt(rounds=12, prefix=b"2b"),
            ).decode("ascii")
    if not hashed.startswith(("$2a$", "$2b$", "$2y$")):
        raise RuntimeError("hash is not bcrypt")
    return hashed


def main() -> int:
    password = os.environ.get("QUAY_ADMIN_PASSWORD", "")
    if not password:
        print("QUAY_ADMIN_PASSWORD is empty", file=sys.stderr)
        return 1
    try:
        print(hash_password(password))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
