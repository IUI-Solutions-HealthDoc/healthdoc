import importlib.util
import plistlib
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "deploy" / "render_abdm_launchagent.py"
SPEC = importlib.util.spec_from_file_location("abdm_launchagent", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_launchagent_runs_exact_existing_tunnel_with_supervision_not_a_bare_binary():
    tunnel = uuid.uuid4()
    config = Path("/private/example user/config & tunnel.yml")
    result = plistlib.loads(MODULE.render(
        executable=Path("/opt/homebrew/bin/cloudflared"), config=config,
        tunnel_id=tunnel, log_dir=Path("/private/test logs"),
    ))
    assert result["ProgramArguments"] == [
        "/opt/homebrew/bin/cloudflared", "--no-autoupdate", "tunnel", "--config",
        str(config), "run", str(tunnel),
    ]
    assert result["KeepAlive"] is True and result["RunAtLoad"] is True
    assert result["ThrottleInterval"] >= 5
    assert result["Label"] == "com.healthdoc.abdm-tunnel"
    assert result["StandardErrorPath"].startswith("/private/test logs/")
    assert "EnvironmentVariables" not in result
    assert "--token" not in result["ProgramArguments"]


@pytest.mark.parametrize("field", ["executable", "config", "log_dir"])
def test_renderer_refuses_paths_dependent_on_launchd_working_directory(field):
    args = dict(executable=Path("/bin/cloudflared"), config=Path("/private/config.yml"),
                tunnel_id=uuid.uuid4(), log_dir=Path("/private/logs"))
    args[field] = Path("relative/path")
    with pytest.raises(ValueError, match="absolute"):
        MODULE.render(**args)


def test_cli_refuses_to_overwrite_existing_custom_service(tmp_path):
    output = tmp_path / "existing.plist"
    original = b"An existing user-managed service must be preserved."
    output.write_bytes(original)
    result = subprocess.run(
        [sys.executable, str(PATH), "--executable", "/bin/cloudflared",
         "--config", "/private/config.yml", "--tunnel-id", str(uuid.uuid4()),
         "--log-dir", "/private/logs", "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "FileExistsError" in result.stderr
    assert output.read_bytes() == original


def test_cli_renders_without_reading_private_config_or_starting_tunnel(tmp_path):
    output = tmp_path / "new.plist"
    # None of these input paths exists: rendering must not inspect credentials,
    # create log directories or execute the supplied binary.
    executable = tmp_path / "not-installed-cloudflared"
    config = tmp_path / "private-config.yml"
    logs = tmp_path / "logs"
    result = subprocess.run(
        [sys.executable, str(PATH), "--executable", str(executable),
         "--config", str(config), "--tunnel-id", str(uuid.uuid4()),
         "--log-dir", str(logs), "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert plistlib.loads(output.read_bytes())["ProgramArguments"][0] == str(executable)
    assert not executable.exists() and not config.exists() and not logs.exists()
