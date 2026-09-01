/** @type {import('next').NextConfig} */

// Next's dev server refuses requests whose Origin is not localhost — including
// the HMR websocket. On a LAN address the handshake fails, and because the dev
// runtime bootstraps through that socket the page never hydrates: every screen
// renders its server HTML and then sits there, controls frozen in their initial
// state. It presents as "the login button is stuck disabled", not as a network
// error, which is why this is worth naming here.
//
// Env-driven rather than a hardcoded address: the demo host's LAN IP changes
// with the network. Production builds have no HMR and no origin check, so this
// affects `next dev` only.
const devOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig = {
  reactStrictMode: true,
  // Keep tracing rooted in this package (avoid picking up ~/package-lock.json).
  outputFileTracingRoot: process.cwd(),
  ...(devOrigins.length > 0 ? { allowedDevOrigins: devOrigins } : {}),
};

export default nextConfig;
