"""Archive current local callback containers before recreation; never print log contents.

Output can contain sensitive historical logs. Keep it private and ignored, not
in a PR/support attachment. This archives existing evidence; it cannot recover
logs from already-deleted containers.
"""

import argparse
import os
import subprocess
from pathlib import Path


def archive(output: Path) -> None:
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for container in ("healthdoc-nginx-1", "healthdoc-backend-1"):
        with (output / f"{container}.stdout.log").open("xb") as stdout:
            with (output / f"{container}.stderr.log").open("xb") as stderr:
                os.fchmod(stdout.fileno(), 0o600)
                os.fchmod(stderr.fileno(), 0o600)
                result = subprocess.run(
                    ["docker", "logs", "--timestamps", container], stdout=stdout, stderr=stderr,
                    timeout=60, check=False,
                )
        if result.returncode:
            raise RuntimeError(f"Archive failed for {container}; do not recreate it")
    print(f"Archived both containers privately under {output}; no log bodies printed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory inside an existing private backup directory")
    archive(parser.parse_args().output)
