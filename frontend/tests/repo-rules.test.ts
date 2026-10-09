import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "lib"];

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) files(full, out);
    else if (/\.(ts|tsx|css|mjs)$/.test(name)) out.push(full);
  }
  return out;
}

const sources = SOURCE_DIRS.flatMap((d) => files(join(ROOT, d))).concat(join(ROOT, "next.config.mjs"));
const pkg = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf-8")) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };

describe("repository rules (Day 6, section 0)", () => {
  it("scans the real source tree", () => {
    expect(sources.length).toBeGreaterThan(25);
  });
  it("uses no dangerouslySetInnerHTML and no innerHTML anywhere", () => {
    const offenders = sources.filter((f) => /dangerouslySetInnerHTML|\.innerHTML\s*=|insertAdjacentHTML|document\.write/.test(readFileSync(f, "utf-8")));
    expect(offenders).toEqual([]);
  });
  it("renders no Markdown or HTML library", () => {
    const banned = /(react-markdown|markdown-it|marked|remark|rehype|showdown|snarkdown|micromark|mdx|dompurify|sanitize-html|html-react-parser)/;
    expect(Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).filter((n) => banned.test(n))).toEqual([]);
    const importers = sources.filter((f) => /from\s+["'](react-markdown|markdown-it|marked|remark|rehype|showdown|dompurify|sanitize-html|html-react-parser)/.test(readFileSync(f, "utf-8")));
    expect(importers).toEqual([]);
  });
  it("adds no runtime dependency and only vitest and @playwright/test as development dependencies", () => {
    expect(Object.keys(pkg.dependencies).sort()).toEqual(["next", "react", "react-dom"]);
    const dev = Object.keys(pkg.devDependencies).filter((n) => !n.startsWith("@types/") && n !== "typescript").sort();
    expect(dev).toEqual(["@playwright/test", "vitest"]);
  });
  it("has no chart library and no state library", () => {
    const banned = ["recharts", "chart.js", "d3", "victory", "nivo", "echarts", "plotly", "redux", "zustand", "mobx", "jotai", "recoil", "swr", "react-query", "@tanstack"];
    const all = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(all.filter((n) => banned.some((b) => n.includes(b)))).toEqual([]);
  });
  it("calls the API only through the same-origin /api rewrite (127.0.0.1 in the rewrite, no CORS change)", () => {
    const config = readFileSync(join(ROOT, "next.config.mjs"), "utf-8");
    expect(config).toContain("/api/:path*");
    expect(config).toContain("http://127.0.0.1:8000");
    expect(config).not.toMatch(/https?:\/\/localhost/);
    const direct = sources.filter((f) => /https?:\/\/(127\.0\.0\.1|localhost)/.test(readFileSync(f, "utf-8")) && !f.endsWith("next.config.mjs"));
    expect(direct).toEqual([]);
  });
  it("never computes DDI, NBE, direction or stance in the browser", () => {
    const risky = sources.filter((f) => /(computeDdi|calculateDdi|bandFor|assessDdi|computeNbe|computeDirection|deriveStance|stanceFor)\s*\(/.test(readFileSync(f, "utf-8")));
    expect(risky).toEqual([]);
  });
  it("writes no file with a byte-order mark", () => {
    const bom = sources.filter((f) => readFileSync(f)[0] === 0xef && readFileSync(f)[1] === 0xbb && readFileSync(f)[2] === 0xbf);
    expect(bom).toEqual([]);
  });
});
