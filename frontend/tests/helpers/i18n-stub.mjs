import { readFileSync } from "node:fs";
import ts from "typescript";

// Keep component tests tied to the actual English catalogue while exercising
// state and effects without mounting the browser locale store.
const source = readFileSync(new URL("../../src/lib/i18n/messages/en.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const catalogue = {};
new Function("exports", code)(catalogue);

function fill(key, vars) {
  let value = catalogue.en[key];
  if (value === undefined) throw new Error(`Missing English translation: ${key}`);
  for (const [name, replacement] of Object.entries(vars ?? {})) {
    value = value.replaceAll(`{${name}}`, String(replacement));
  }
  return value;
}

// Same signature as the real translate(key, locale?, vars?).
export function translate(key, _locale, vars) {
  return fill(key, vars);
}

const locale = {
  locale: "en",
  t: fill,
  localizeField: (english) => english,
  setLocale: () => {},
  locales: [{ code: "en", label: "English", nativeLabel: "English" }],
};

export const i18nStub = {
  useLocale: () => locale,
  translate,
  localizeField: (english) => english,
};
