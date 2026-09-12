"""Build the local ABDM ECDH helper with a checksum-pinned BC dependency."""

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
VERSION = "1.86"
SHA256 = "2af190b300cbb0b35e248ccf5f4a06b6072030aeb3da7a98ec73abe5b4cb371f"
URL = f"https://repo.maven.apache.org/maven2/org/bouncycastle/bcprov-jdk18on/{VERSION}/bcprov-jdk18on-{VERSION}.jar"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit", action="store_true", help="Check this pinned Maven dependency against OSV"
    )
    args = parser.parse_args()
    if args.audit:
        request = urllib.request.Request(
            "https://api.osv.dev/v1/query",
            data=json.dumps(
                {
                    "package": {"name": "org.bouncycastle:bcprov-jdk18on", "ecosystem": "Maven"},
                    "version": VERSION,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            findings = json.load(response).get("vulns", [])
        if findings:
            raise SystemExit("Bouncy Castle advisories: " + ", ".join(v["id"] for v in findings))
        print(f"Bouncy Castle {VERSION}: no known advisories in OSV")
        return
    RUNTIME.mkdir(exist_ok=True)
    jar = RUNTIME / "bcprov.jar"
    data = jar.read_bytes() if jar.exists() else urllib.request.urlopen(URL, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("Bouncy Castle checksum mismatch; refusing to build")
    if not jar.exists():
        jar.write_bytes(data)
    subprocess.run(
        [
            os.environ.get("HEALTHDOC_JAVAC", "javac"),
            "--release",
            "17",
            "-cp",
            str(jar),
            "-d",
            str(RUNTIME),
            str(ROOT / "HealthDocEcdh.java"),
        ],
        check=True,
    )
    print(f"ABDM ECDH helper built with checksum-verified Bouncy Castle {VERSION}")


if __name__ == "__main__":
    main()
