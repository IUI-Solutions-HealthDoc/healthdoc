"""ABHA's external representation, independent of its digits-only storage."""


def hyphenate_abha(stored: str) -> str:
    """Restore the 2-4-4-4 representation before lookup or RSA encryption.

    Do not remove arbitrary characters to turn an invalid identifier into a
    different, plausible one. Public routes validate the input separately.
    """
    digits = stored.replace("-", "").strip()
    if len(digits) != 14 or not digits.isascii() or not digits.isdigit():
        return stored
    return f"{digits[:2]}-{digits[2:6]}-{digits[6:10]}-{digits[10:]}"
