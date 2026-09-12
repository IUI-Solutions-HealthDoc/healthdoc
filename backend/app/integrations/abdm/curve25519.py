"""Bounded pipe to BC's Curve25519 ECDH; keys never enter argv or log messages."""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.common.config import get_settings

DEFAULT_RUNTIME = Path(__file__).resolve().parents[3] / "crypto" / ".runtime"
STORAGE_PREFIX = "bc-curve25519-v1:"


class CurveError(ValueError):
    pass


def invoke(*fields: str) -> list[str]:
    settings = get_settings()
    runtime = (
        Path(settings.healthdoc_ecdh_runtime)
        if settings.healthdoc_ecdh_runtime
        else DEFAULT_RUNTIME
    )
    payload = "\n".join(fields) + "\n"
    if len(payload) > 4096 or any("\n" in f for f in fields):
        raise CurveError("Invalid ECDH input")
    try:
        result = subprocess.run(
            [
                settings.healthdoc_java,
                "-Xmx64m",
                "-XX:-UsePerfData",
                "-cp",
                os.pathsep.join([str(runtime), str(runtime / "bcprov.jar")]),
                "HealthDocEcdh",
            ],
            input=payload,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CurveError("ABDM ECDH runtime unavailable") from exc
    if result.returncode or len(result.stdout) > 2048:
        raise CurveError("ABDM ECDH operation failed; check runtime or key format")
    return result.stdout.splitlines()


@dataclass(frozen=True)
class PrivateKey:
    scalar: bytes = field(repr=False)

    def private_bytes_raw(self) -> bytes:
        return self.scalar

    def exchange(self, peer: bytes) -> bytes:
        result = invoke(
            "derive", base64.b64encode(self.scalar).decode(), base64.b64encode(peer).decode()
        )
        if len(result) != 1:
            raise CurveError("Malformed ECDH result")
        shared = base64.b64decode(result[0], validate=True)
        if len(shared) != 32:
            raise CurveError("Malformed ECDH result")
        return shared


def generate() -> tuple[PrivateKey, bytes]:
    result = invoke("generate")
    if len(result) != 2:
        raise CurveError("Malformed ECDH key material")
    scalar, public = (base64.b64decode(value, validate=True) for value in result)
    if len(scalar) != 32 or len(public) != 65 or public[0] != 4:
        raise CurveError("Malformed ECDH key material")
    return PrivateKey(scalar), public


def serialize(key: PrivateKey) -> str:
    return STORAGE_PREFIX + base64.b64encode(key.scalar).decode()


def deserialize(value: str) -> PrivateKey:
    if not value.startswith(STORAGE_PREFIX):
        raise CurveError("Legacy transfer key is incompatible; initiate a new consented transfer")
    try:
        raw = base64.b64decode(value[len(STORAGE_PREFIX) :], validate=True)
    except ValueError as exc:
        raise CurveError("Invalid stored transfer key") from exc
    if len(raw) != 32:
        raise CurveError("Invalid stored transfer key")
    return PrivateKey(raw)
