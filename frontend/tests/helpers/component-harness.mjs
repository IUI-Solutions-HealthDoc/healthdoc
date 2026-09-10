import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

export function compile(url, dependencies) {
  const code = ts.transpileModule(readFileSync(url, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("require", "exports", code)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, exports);
  return exports;
}

/** Executes actual TSX hooks/keys/cleanup, not layout, hydration or SSO. */
export function componentHarness(build) {
  const fibers = new Map();
  let fiber, cursor, seen;
  const react = {
    useState(initial) {
      const owner = fiber, i = cursor++;
      if (!(i in owner.hooks)) owner.hooks[i] = typeof initial === "function" ? initial() : initial;
      return [owner.hooks[i], (v) => { owner.hooks[i] = typeof v === "function" ? v(owner.hooks[i]) : v; }];
    },
    useRef(initial) { const i = cursor++; return fiber.hooks[i] ??= { current: initial }; },
    useEffect(effect, deps) {
      const i = cursor++, old = fiber.hooks[i];
      if (!old || deps.some((v, n) => !Object.is(v, old.deps[n]))) fiber.hooks[i] = { effect, deps, cleanup: old?.cleanup, pending: true };
    },
    useCallback(callback, deps) {
      const i = cursor++, old = fiber.hooks[i];
      if (!old || deps.some((v, n) => !Object.is(v, old.deps[n]))) fiber.hooks[i] = { value: callback, deps };
      return fiber.hooks[i].value;
    },
  };
  const jsx = (type, props, key) => ({ type, props, key });
  const component = build({ react, "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" } });
  function expand(node, path) {
    if (Array.isArray(node)) return node.map((child, i) => expand(child, `${path}/${i}`));
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") {
      const id = `${path}/${node.type.name}/${node.key ?? ""}`;
      seen.add(id); fiber = fibers.get(id) ?? { hooks: [] }; fibers.set(id, fiber); cursor = 0;
      return expand(node.type(node.props), id);
    }
    return { ...node, props: { ...node.props, children: expand(node.props?.children, `${path}/children`) } };
  }
  return {
    render(props) {
      seen = new Set(); const tree = expand({ type: component, props }, "root");
      for (const [id, owner] of fibers) if (!seen.has(id)) {
        owner.hooks.forEach((hook) => hook?.cleanup?.()); fibers.delete(id);
      }
      return tree;
    },
    effects() {
      for (const owner of fibers.values()) for (const hook of owner.hooks) if (hook?.pending) {
        hook.cleanup?.(); hook.cleanup = hook.effect(); hook.pending = false;
      }
    },
  };
}
export const flush = () => new Promise((resolve) => setImmediate(resolve));
export function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return tree && typeof tree === "object" ? [tree, ...nodes(tree.props?.children)] : [];
}
export function content(tree) {
  if (Array.isArray(tree)) return tree.map(content).join(" ");
  return tree && typeof tree === "object" ? content(tree.props?.children) : String(tree ?? "");
}
