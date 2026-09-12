# ABDM transfer cryptography runtime

HealthDoc now uses Bouncy Castle's named `curve25519`, as used by Fidelius,
not RFC7748 X25519. EC operations use BC; Python retains HKDF-SHA256 and
AES-256-GCM. The nonce XOR's first 20 bytes are salt and last 12 bytes IV.

## Install and verify

Docker builds the helper and installs the JDK. Host tests require JDK 17+
(CI/Docker use 21), then from the repository root:

```sh
make abdm-crypto
make test-pg
make audit-deps
```

If Java is not on PATH, set `HEALTHDOC_JAVA` to its `bin/java` and
`HEALTHDOC_JAVAC` to its `bin/javac` before these commands. Generated classes
and the downloaded JAR are ignored. `build.py` refuses a checksum mismatch;
`make audit-deps` includes this Maven dependency, not just npm/pip packages.

Pinned dependency: `org.bouncycastle:bcprov-jdk18on:1.86`.
SHA-256: `2af190b300cbb0b35e248ccf5f4a06b6072030aeb3da7a98ec73abe5b4cb371f`.

The runtime accepts full uncompressed points and X.509 keys only on the exact
curve; BC validates points. It refuses bare X25519 bytes, fake 33-byte prefixes,
foreign curves and malformed keys. Keys travel through bounded stdin/stdout
pipes, never command arguments, network services or temporary key files. The
helper receives no clinical plaintext. Each invocation has a timeout and heap
limit and emits only a generic error on failure.

## Evidence and compatibility

- The public Fidelius README known-answer vector is tested in both directions,
  with raw-point and X.509 keys. Tests fail if the actual JVM helper is absent.
- `python -m scripts.verify_abdm_crypto_reference --fidelius-lib PATH` (inside
  `backend`) cross-checks fresh synthetic exchanges against the independent
  Fidelius CLI at revision `4d9b4a5f65d61607dafcea3e28e3d257e425fcd9`.
  Its bundled old dependencies are reference-test-only, never deployed.
- Encrypted stored private keys carry a `bc-curve25519-v1:` marker. Old
  unversioned X25519 keys are deliberately not reinterpreted. Pending legacy
  transfers need a newly authorized request; no automatic resend or expiry
  extension occurs. Existing frozen outbound ciphertext must not be relabelled.
- Self/reference interoperability is **not live NHA acceptance** or
  certification. Preserve the separate milestone case ledger.

References: https://github.com/mgrmtech/fidelius-cli and
https://github.com/NHA-ABDM/ABDM-wrapper.
