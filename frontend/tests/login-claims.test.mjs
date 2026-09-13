import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, nodes } from "./helpers/component-harness.mjs";

function assertEvidenceBoundCopy(text) {
  assert.doesNotMatch(text, /FIPS|DPDP Compliant|Immutable audit|End-to-End|Full Orthanc|v2\.4|All access is logged/i);
}

test("rendered auth banner does not imply certification or configured optional services", () => {
  const ui = componentHarness((runtime) => compile(
    new URL("../src/app/(auth)/layout.tsx", import.meta.url),
    {
      ...runtime,
      "lucide-react": { ShieldCheck: "icon", Activity: "icon", Award: "icon", Lock: "icon" },
      "@/components/common/HealthDocBrand": { HealthDocBrand: "brand" },
    },
  ).default);
  const text = content(ui.render({ children: "Login form" }));
  assertEvidenceBoundCopy(text);
  assert.match(text, /M1\/M2\/M3 sandbox verification in progress/);
  assert.match(text, /Imaging integration requires facility setup/);
  assert.match(text, /Login form/);
});

test("rendered sign-in keeps the real identity flow without unsupported compliance badges", async () => {
  const calls = [];
  const ui = componentHarness((runtime) => compile(
    new URL("../src/features/login/LoginScreen.tsx", import.meta.url),
    {
      ...runtime,
      "next/navigation": { useSearchParams: () => new URLSearchParams() },
      "@/components/ui/Button": { Button: "button" },
      "@/components/common/HealthDocBrand": { HealthDocBrand: "brand" },
      "@/lib/auth/keycloak": {
        isKeycloakConfigured: () => true,
        loginWithKeycloak: async (url) => calls.push(url),
      },
      "@/lib/auth/routes": { getDefaultRouteForRole: () => "/doctor/dashboard" },
      "@/providers/auth-provider": { useAuth: () => ({ isAuthenticated: false, isLoading: false, user: null }) },
    },
  ).LoginScreen);
  const tree = ui.render({});
  assertEvidenceBoundCopy(content(tree));
  const button = nodes(tree).find((node) => node.type === "button");
  assert.equal(content(button), "Sign in with Keycloak");
  assert.equal(button.props.disabled, false);
  assert.deepEqual(calls, [], "Rendering the page must not start a login");
});
