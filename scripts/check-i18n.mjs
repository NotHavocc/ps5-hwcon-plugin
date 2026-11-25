import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/index.tsx", import.meta.url),
  "utf8",
);
const catalogSource = readFileSync(
  new URL("../src/i18n.ts", import.meta.url),
  "utf8",
);
const catalogBlock = catalogSource.match(
  /const sv: Record<string, string> = \{([\s\S]*?)\n\};/,
);

if (!catalogBlock) {
  throw new Error("The Swedish catalog was not found.");
}

const calls = new Set(
  [...source.matchAll(/\bt\("((?:\\.|[^"\\])*)"/g)].map((match) => match[1]),
);
const catalogKeys = new Set();
for (const match of catalogBlock[1].matchAll(
  /^\s+(?:"((?:\\.|[^"\\])*)"|([A-Za-z_][A-Za-z0-9_]*)):/gm,
)) {
  catalogKeys.add(match[1] ?? match[2]);
}

const missing = [...calls].filter((key) => !catalogKeys.has(key));
if (missing.length) {
  throw new Error(`Missing Swedish catalog entries: ${missing.join(", ")}`);
}

console.log(`Swedish catalog covers ${calls.size} UI messages.`);
