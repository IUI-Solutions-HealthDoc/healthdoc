import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), "utf8");
}

test("the canonical HealthDoc logo is a real PNG", async () => {
  const sourceLogo = await readFile(new URL("../splash-icon.png", root));
  const logo = await readFile(new URL("public/healthdoc-logo.png", root));
  const keycloakLogo = await readFile(
    new URL("../infra/keycloak/themes/healthdoc/login/resources/img/healthdoc-logo.png", root),
  );
  assert.deepEqual([...logo.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.deepEqual(logo, sourceLogo, "web logo drifted from the supplied source image");
  assert.deepEqual(keycloakLogo, sourceLogo, "Keycloak logo drifted from the supplied source image");
});

test("product surfaces use the canonical HealthDoc brand", async () => {
  for (const path of [
    "src/features/login/LoginScreen.tsx",
    "src/components/common/Navbar.tsx",
    "src/components/common/Sidebar.tsx",
    "src/components/common/MainLayout.tsx",
    "src/features/queue-display/QueueDisplayBoard.tsx",
  ]) {
    assert.match(await source(path), /HealthDocBrand/, `${path} lost the product brand`);
  }

  assert.match(await source("src/app/layout.tsx"), /healthdoc-logo\.png/);
  assert.match(await source("src/app/manifest.ts"), /healthdoc-logo\.png/);
  assert.match(await source("src/proxy.ts"), /pathname === "\/healthdoc-logo\.png"/);
  assert.match(await source("src/proxy.ts"), /pathname === "\/manifest\.webmanifest"/);
  assert.match(await source("electron/main.ts"), /healthdoc-logo\.png/);
  assert.match(
    await source("src/components/shared/labreportviewer/data/report.ts"),
    /healthdoc-logo\.png/,
  );
});
