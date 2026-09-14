"""Render (never install) a user-level launchd agent for an existing ABDM tunnel.

Keep the existing tunnel configuration/credential file private. This renderer
does not create tunnels, change DNS/ingress, read credentials or run a shell.
"""

import argparse
import plistlib
import uuid
from pathlib import Path

LABEL = "com.healthdoc.abdm-tunnel"


def render(*, executable: Path, config: Path, tunnel_id: uuid.UUID, log_dir: Path) -> bytes:
    for path in (executable, config, log_dir):
        if not path.is_absolute():
            raise ValueError("Executable, config and log directory paths must be absolute")
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [
            str(executable), "--no-autoupdate", "tunnel", "--config", str(config),
            "run", str(tunnel_id),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / f"{LABEL}.out.log"),
        "StandardErrorPath": str(log_dir / f"{LABEL}.err.log"),
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tunnel-id", type=uuid.UUID, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = render(executable=args.executable, config=args.config,
                        tunnel_id=args.tunnel_id, log_dir=args.log_dir)
        # Exclusive create: never overwrite an installed/custom service.
        with args.output.open("xb") as output:
            output.write(result)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"LaunchAgent render refused: {type(exc).__name__}\n")
    print(f"Rendered {LABEL}; installation and ingress validation are separate steps.")
