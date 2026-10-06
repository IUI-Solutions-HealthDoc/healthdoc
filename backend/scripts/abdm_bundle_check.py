"""Check FHIR bundles through ABDM's transfer chain, offline, synthetic data only.

The chain a record travels (M2 HIP -> HIE-CM -> M3 HIU):

  1. build     fhir/builder.build_clinical_bundle: one NRCeS document Bundle
  2. encode    hip/service.encrypt_bundle_for_hiu: Fidelius ECDH on Curve25519
               with a fresh HIP key pair and 32-byte nonce; the XOR of both
               nonces gives the HKDF salt (first 20 bytes) and the GCM IV
               (last 12); HKDF-SHA256 with empty info gives the AES-256 key;
               AES-256-GCM, no AAD, tag appended, base64. checksum = MD5 hex
               of the plaintext.
  3. page      the JSON the HIP POSTs to the HIU's dataPushUrl:
               {pageNumber, pageCount, transactionId, entries: [{content,
               media: application/fhir+json, checksum, careContextReference}],
               keyMaterial: {cryptoAlg, curve, dhPublicKey: {expiry,
               parameters, keyValue}, nonce}}
  4. decode    the HIU's half of the same derivation (hiu/service.receive_bundle)
               with its private key and nonce, then the checksum
  5. validate  hiu/records.validate_document: the checks HealthDoc's HIU applies
               to every received document (one final Composition, a consented
               NRCeS profile and date range, one Patient carrying the consented
               ABHA, every subject pointing at it)

Every step here calls the production function, so a pass means HealthDoc's
encoder and decoder agree and its HIU would accept what its HIP sends. It is
not evidence that NHA or another HIP agrees: that is what the live sandbox
round trips are for.

  roundtrip [BUNDLE ...]   build/encode/page/decode/validate every sample
                           (or the given bundle files); --out DIR writes each
                           page, its synthetic HIU keys and the decoded bundle
  decode PAGE --keys KEYS  decode a page with HIU keys written by roundtrip
  inspect BUNDLE           summarise a bundle's Composition and resources

NRCeS profile conformance is the HL7 validator's job, run offline, e.g.:
  docker run --rm --network none -v <cache>:/root/.fhir -v <validator.jar>:/v.jar \\
    -v <dir>:/work eclipse-temurin:17-jre java -jar /v.jar /work/<bundle>.json \\
    -version 4.0.1 -ig ndhm.in#6.5.0 -tx n/a

Never point this at real patient data. It refuses to read the database, and
the keys it writes are throwaway synthetic keys.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.integrations.abdm import curve25519, hi_crypto
from app.integrations.abdm.fhir.builder import validate_min
from app.integrations.abdm.hip import service as hip_service
from app.integrations.abdm.hiu import records

MEDIA = "application/fhir+json"
ABHA_SYSTEMS = records.ABHA_SYSTEMS


def _hi_type(bundle: dict) -> str | None:
    composition = (bundle.get("entry") or [{}])[0].get("resource", {})
    for profile in (composition.get("meta") or {}).get("profile") or []:
        name = str(profile).split("|")[0].removeprefix(records.PROFILE_ROOT)
        if name in records.PROFILES:
            return records.PROFILES[name]
    return None


def _abha(bundle: dict) -> str | None:
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Patient":
            for identifier in resource.get("identifier") or []:
                if identifier.get("system") in ABHA_SYSTEMS:
                    return str(identifier.get("value"))
    return None


def _grant(hi_type: str, reference: str, abha: str) -> SimpleNamespace:
    """A consent that permits exactly this document, as the HIU's grant does."""
    number = abha.replace("-", "")
    return SimpleNamespace(
        artefact=SimpleNamespace(
            hi_types=[hi_type],
            date_range_from=datetime(1900, 1, 1, tzinfo=UTC),
            date_range_to=datetime(2100, 1, 1, tzinfo=UTC),
        ),
        request=SimpleNamespace(abha_address=abha),
        patient=SimpleNamespace(abha_number=number if number.isdigit() else None),
        detail={"careContexts": [{"careContextReference": reference}]},
        hip_id="SYNTHETIC-HIP",
    )


def encode(bundle: dict, *, reference: str, page_number: int = 1, page_count: int = 1):
    """HIP side: returns (page, hiu_keys) for a fresh synthetic HIU key."""
    hiu = hi_crypto.generate_key_material()
    ciphertext, key_material, checksum = hip_service.encrypt_bundle_for_hiu(
        bundle, hiu_public_key_b64=hiu.public_key_b64, hiu_nonce_b64=hiu.nonce_b64
    )
    page = {
        "pageNumber": page_number,
        "pageCount": page_count,
        "transactionId": "synthetic-transaction",
        "entries": [
            {"content": ciphertext, "media": MEDIA, "checksum": checksum, "careContextReference": reference}
        ],
        "keyMaterial": key_material,
    }
    keys = {"private_key": curve25519.serialize(hiu.private_key), "nonce": hiu.nonce_b64,
            "warning": "synthetic throwaway HIU key; never use for real data"}
    return page, keys


def decode(page: dict, keys: dict) -> list[dict]:
    """HIU side: every entry decrypted and checksum-checked, as receive_bundle does."""
    material = page["keyMaterial"]
    private_key = curve25519.deserialize(keys["private_key"])
    aes_key, iv = hi_crypto.derive_shared_key(
        private_key=private_key,
        peer_public_key_b64=material["dhPublicKey"]["keyValue"],
        our_nonce_b64=keys["nonce"],
        peer_nonce_b64=material["nonce"],
    )
    out = []
    for entry in page["entries"]:
        plaintext = hi_crypto.decrypt(entry["content"], aes_key=aes_key, iv=iv)
        md5 = hashlib.md5(plaintext.encode(), usedforsecurity=False).digest()
        sha = hashlib.sha256(plaintext.encode()).digest()
        accepted = {md5.hex(), base64.b64encode(md5).decode(), sha.hex(), base64.b64encode(sha).decode()}
        out.append({
            "reference": entry.get("careContextReference"),
            "media": entry.get("media"),
            "checksum_ok": entry.get("checksum") in accepted,
            "bundle": json.loads(plaintext),
        })
    return out


def check(bundle: dict, decoded: dict, *, reference: str) -> list[str]:
    """Why the HIU would refuse this document; empty when it would accept it."""
    problems = [f"structure: {p}" for p in validate_min(bundle)]
    if decoded["bundle"] != bundle:
        problems.append("decode: decrypted bundle differs from the one encoded")
    if not decoded["checksum_ok"]:
        problems.append("checksum: declared checksum does not match the plaintext")
    if decoded["media"] != MEDIA:
        problems.append(f"media: {decoded['media']!r} is not {MEDIA}")
    hi_type, abha = _hi_type(bundle), _abha(bundle)
    if hi_type is None:
        problems.append("profile: Composition declares no NRCeS document profile the HIU reads")
    if abha is None:
        problems.append("patient: no ABHA identifier, so no HIU can match the patient")
    if hi_type and abha:
        try:
            records.validate_document(decoded["bundle"], _grant(hi_type, reference, abha), reference)
        except records.RecordRefused as exc:
            problems.append(f"HIU: {exc}")
    return problems


def inspect(bundle: dict) -> str:
    composition = (bundle.get("entry") or [{}])[0].get("resource", {})
    kinds = Counter((e.get("resource") or {}).get("resourceType") for e in bundle.get("entry") or [])
    lines = [
        f"profile   {', '.join((composition.get('meta') or {}).get('profile') or ['-'])}",
        f"HI type   {_hi_type(bundle) or 'unknown'}",
        f"type      {json.dumps(composition.get('type'))}",
        f"date      {composition.get('date')}",
        f"sections  {[s.get('title') for s in composition.get('section') or []]}",
        f"resources {dict(kinds)}",
        f"ABHA id   {'present' if _abha(bundle) else 'MISSING'}",
    ]
    return "\n".join(lines)


def _samples() -> dict[str, dict]:
    from scripts.generate_abdm_fhir_samples import _samples as built

    return built()


def _roundtrip(args) -> int:
    bundles = (
        {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in args.bundles}
        if args.bundles
        else _samples()
    )
    failed = 0
    for pos, (name, bundle) in enumerate(bundles.items(), start=1):
        reference = f"synthetic/{name}"
        page, keys = encode(bundle, reference=reference, page_number=pos, page_count=len(bundles))
        decoded = decode(page, keys)[0]
        problems = check(bundle, decoded, reference=reference)
        size = len(page["entries"][0]["content"])
        print(f"{'PASS' if not problems else 'FAIL'}  {name:<24} {_hi_type(bundle) or '?':<20} "
              f"{size:>7} B ciphertext, checksum {page['entries'][0]['checksum']}")
        for problem in problems:
            print(f"      - {problem}")
        failed += bool(problems)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"{name}.page.json").write_text(json.dumps(page, indent=2), encoding="utf-8")
            (args.out / f"{name}.hiu-keys.json").write_text(json.dumps(keys, indent=2), encoding="utf-8")
            (args.out / f"{name}.decoded.json").write_text(json.dumps(decoded["bundle"], indent=2),
                                                           encoding="utf-8")
    print(f"\n{len(bundles) - failed} of {len(bundles)} passed")
    return 1 if failed else 0


def _decode(args) -> int:
    page = json.loads(args.page.read_text(encoding="utf-8"))
    keys = json.loads(args.keys.read_text(encoding="utf-8"))
    failed = 0
    for item in decode(page, keys):
        problems = check(item["bundle"], item, reference=item["reference"])
        print(f"{'PASS' if not problems else 'FAIL'}  {item['reference']}")
        print("      " + inspect(item["bundle"]).replace("\n", "\n      "))
        for problem in problems:
            print(f"      - {problem}")
        failed += bool(problems)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            name = str(item["reference"]).replace("/", "_")
            (args.out / f"{name}.decoded.json").write_text(json.dumps(item["bundle"], indent=2), encoding="utf-8")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rt = sub.add_parser("roundtrip", help="build, encode, decode and validate")
    rt.add_argument("bundles", nargs="*", type=Path)
    rt.add_argument("--out", type=Path)
    dc = sub.add_parser("decode", help="decode a page with synthetic HIU keys")
    dc.add_argument("page", type=Path)
    dc.add_argument("--keys", type=Path, required=True)
    dc.add_argument("--out", type=Path)
    ins = sub.add_parser("inspect", help="summarise a bundle")
    ins.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    if args.command == "roundtrip":
        return _roundtrip(args)
    if args.command == "decode":
        return _decode(args)
    print(inspect(json.loads(args.bundle.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
