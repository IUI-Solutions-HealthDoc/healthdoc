import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function initializer(file, name) {
  const source = ts.createSourceFile(file, readFileSync(new URL(file, import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let found;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === name) found = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(found, `${name} must be present; an empty parse is not a passing gate`);
  return found;
}

function literal(node) {
  if (ts.isAsExpression(node)) return literal(node.expression);
  if (ts.isStringLiteral(node)) return node.text;
  if (ts.isNumericLiteral(node)) return Number(node.text);
  if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
  if (ts.isArrayLiteralExpression(node)) return node.elements.map(literal);
  if (ts.isObjectLiteralExpression(node)) return Object.fromEntries(node.properties.map((p) => {
    assert.ok(ts.isPropertyAssignment(p));
    return [p.name.getText().replaceAll('"', ""), literal(p.initializer)];
  }));
  throw new Error(`Unsupported matrix literal ${node.getText()}`);
}

const dashboards = literal(initializer("../e2e/dashboards.smoke.mjs", "ROLE_DASHBOARDS"));
const roles = literal(initializer("../src/config/roles.ts", "ROLES"));

test("every role's sidebar entries have exact dashboard smoke coverage", () => {
  const nav = initializer("../src/components/common/Sidebar.tsx", "NAV_ITEMS");
  assert.ok(ts.isArrayLiteralExpression(nav) && nav.elements.length > 0);
  const entries = nav.elements.map((item) => {
    const props = new Map(item.properties.map((p) => [p.name.getText(), p.initializer]));
    return {
      path: literal(props.get("href")),
      roles: props.get("roles").elements.map((role) => {
        assert.ok(ts.isPropertyAccessExpression(role) && role.expression.getText() === "ROLES");
        assert.ok(roles[role.name.text]);
        return roles[role.name.text];
      }),
    };
  });
  assert.deepEqual(dashboards.map((role) => role.name).sort(), Object.values(roles).sort());
  for (const role of dashboards) {
    assert.deepEqual(role.dashboards.map((screen) => screen.path).sort(),
      entries.filter((entry) => entry.roles.includes(role.name)).map((entry) => entry.path).sort(), role.name);
  }
});

test("admin ABDM smoke requires the mounted delivery queue API", () => {
  const page = dashboards.find((role) => role.name === "admin").dashboards.find((page) => page.path === "/admin/abdm-sync");
  assert.equal(page.expectCalls, true);
  assert.ok(page.requiredRequests.some((request) => request.method === "GET" && request.path === "/api/v1/abdm/operations/jobs"));
});
