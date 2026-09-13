# Supervised local ABDM callback tunnel (macOS)

The sandbox callback hostname must outlive an assistant/terminal session.
HTTP 530 with Cloudflare body `error code: 1033` means no healthy connector
is available. A process named `cloudflared` alone is not proof of a running
tunnel: the previously installed system daemon invoked only the executable,
without `tunnel run` or the intended config.

`scripts/deploy/render_abdm_launchagent.py` renders a separate user LaunchAgent
named `com.healthdoc.abdm-tunnel`. It passes an explicit existing config and
tunnel UUID, starts on login, and is restarted by launchd if it exits. It
does not modify a system daemon, DNS, registration, credentials or ingress.
Run `--help` for the required absolute local paths; render to a new temporary
file, validate it using `plutil -lint`, and review it before installation.

## Install only after validating the existing configuration

1. Run `cloudflared tunnel --config CONFIG ingress validate`. Review the config:
   only the intended callback hostname and `/api/v3/*` should reach nginx;
   all other paths must return 404. Do not route straight to the backend or
   broaden ingress to solve a failing callback.
2. Render the agent using the installed `cloudflared` path, that private config,
   the existing tunnel UUID, and a private user log directory. No credentials
   belong in the plist, command line, repository or review evidence.
3. Install with mode 0600 as
   `~/Library/LaunchAgents/com.healthdoc.abdm-tunnel.plist` only if absent. Back
   up and review any existing target instead of overwriting it blindly.
4. Use `launchctl bootstrap gui/UID ABSOLUTE_PLIST_PATH` for the current numeric
   user ID. Verify `launchctl print gui/UID/com.healthdoc.abdm-tunnel` reports a
   PID, and inspect connector registration logs.
5. Run `bash scripts/abdm_sandbox.sh doctor https://CALLBACK_HOST` for empty
   callback refusal probes, then confirm non-callback public URLs still 404.
   These probes prove reachability/refusal only, not gateway authentication,
   real callback receipt, clinical transfer or milestone completion.
6. For an agreed restart test, use
   `launchctl kickstart -k gui/UID/com.healthdoc.abdm-tunnel`; confirm a new PID
   and recheck public routes. Do not do this during a live consent/transfer.

Rollback stops only this connector using
`launchctl bootout gui/UID ABSOLUTE_PLIST_PATH`. Move the plist to a reviewed
backup location if it should not restart at the next login; retain private
tunnel credentials and other services unchanged.

This user agent depends on the Mac being awake, the user being logged in,
Docker/origin availability, and Internet connectivity. It is **not** a
reboot-before-login guarantee or production high availability. Deploy a
supervised always-on origin and monitoring before relying on unattended
production callbacks. The existing local self-signed-origin exception is
not broadened by this service; production must use verified origin TLS.

Sources: [Cloudflare macOS service guidance](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/macos/),
[Cloudflare 1033 troubleshooting](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/).
