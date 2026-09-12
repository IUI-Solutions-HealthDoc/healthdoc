"""Independent, synthetic-only cross-process check against pinned Fidelius CLI.

Run with --fidelius-lib pointing at the lib directory from revision
4d9b4a5f65d61607dafcea3e28e3d257e425fcd9. Production never invokes this old CLI;
the application uses checksum-pinned BC 1.86. No patient data or network calls.
"""

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

from app.integrations.abdm import hi_crypto


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fidelius-lib", required=True, type=Path)
    args = parser.parse_args()
    java = os.environ.get("HEALTHDOC_JAVA", "java")

    def reference(*fields):
        process = subprocess.run(
            [
                java,
                "-cp",
                str(args.fidelius_lib / "*"),
                "com.mgrm.fidelius.FideliusApplication",
                "-f",
                "/dev/stdin",
            ],
            input="\n".join(fields) + "\n",
            text=True,
            capture_output=True,
            timeout=20,
        )
        if process.returncode or process.stderr:
            raise RuntimeError(
                "Independent reference failed (details withheld to protect key material)"
            )
        return json.loads(process.stdout)

    peer = reference("gkm")
    local = hi_crypto.generate_key_material()
    text = json.dumps({"resourceType": "Bundle", "id": "SYNTHETIC-CRYPTO-ONLY", "entry": []})
    for public_format in ("publicKey", "x509PublicKey"):
        key, iv = hi_crypto.derive_shared_key(
            private_key=local.private_key,
            peer_public_key_b64=peer[public_format],
            our_nonce_b64=local.nonce_b64,
            peer_nonce_b64=peer["nonce"],
        )
        outbound = hi_crypto.encrypt(text, aes_key=key, iv=iv)
        opened = reference(
            "d", outbound, peer["nonce"], local.nonce_b64, peer["privateKey"], local.public_key_b64
        )
        assert opened["decryptedData"] == text, "Reference could not open HealthDoc content"
        inbound = reference(
            "se",
            base64.b64encode(text.encode()).decode(),
            peer["nonce"],
            local.nonce_b64,
            peer["privateKey"],
            local.public_key_b64,
        )
        assert hi_crypto.decrypt(inbound["encryptedData"], aes_key=key, iv=iv) == text
    print("PASS: independent Fidelius <-> HealthDoc, both directions, point and X.509 peer keys")


if __name__ == "__main__":
    main()
