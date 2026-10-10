import { describe, expect, it } from "vitest";

import { VersionComparison, VersionHistory } from "../components/assessment/Cards";
import { assessment, gated, html, region, text } from "./helpers";

const dim = (id: string, score: number, contribution: number, inputs: Array<{ name: string; value: unknown }> = []) => ({
  id, name: `Dimension ${id}`, score, applicable: true, status: "Applicable", weight: 0.1, raw_contribution: contribution, display_contribution: contribution,
  inputs: inputs.map((i) => ({ ...i, source: "observed" as const, default_reason: null })), defaulted_inputs: [], explanation: "e", details: {},
});

const v1 = assessment({ id: "a1", version: 1, is_current: false, is_superseded: true, ddi: 100, band: "critical",
  dimensions: [dim("D4", 0.2, 7.5, [{ name: "power_factor", value: 0.1 }]), dim("D5", 0, 10)] });
const v2 = assessment({ id: "a2", version: 2, ddi: 73.7, band: "high",
  dimensions: [dim("D4", 0.2, 5, [{ name: "power_factor", value: 0.1 }]), dim("D5", 0.6, 4)] });

describe("version comparison (D7-06)", () => {
  it("shows every dimension and penalty of the two scored versions and marks the unchanged D4", () => {
    const m = html(<VersionComparison previous={v1} current={v2} />);
    expect(m).toContain('data-testid="version-compare"');
    expect(region(m, 'data-dim', "D4") ?? "").toContain("");
    expect(m).toMatch(/data-dim="D4" data-unchanged="true"/);
    expect(m).toMatch(/data-dim="D5" data-unchanged="false"/);
    expect(m).toMatch(/data-dim="P1"/);
    expect(text(m)).toContain("v1 (superseded) compared with v2 (current)");
    expect(text(m)).toContain("Synthetic data");
  });

  it("D4 counts as unchanged when its score and inputs are identical even though its contribution was rescaled", () => {
    const m = html(<VersionComparison previous={v1} current={v2} />);
    expect(m).toMatch(/data-dim="D4" data-unchanged="true"/);
    expect(text(m)).toContain("score and inputs unchanged");
  });

  it("an insufficient version shows 'no DDI' and never a number or a table", () => {
    const m = html(<VersionComparison previous={gated({ version: 1, is_current: false })} current={v2} />);
    expect(m).toContain('data-testid="compare-no-ddi"');
    expect(text(m)).toContain("No DDI for v1: INSUFFICIENT EVIDENCE");
    expect(m).not.toContain("compare-table");
    expect(m).not.toContain("data-ddi-value");
    expect(text(m)).not.toMatch(/\d+\.\d/);
  });

  it("renders nothing when the current assessment is not scored (a gated decision shows no contribution anywhere)", () => {
    expect(html(<VersionComparison previous={v1} current={gated({ version: 3 })} />)).toBe("");
  });

  it("the version list offers the comparison only for the versions it is given and never shows a score in the list", () => {
    const versions = [{ id: "a2", version: 2, state: "scored", created_at: "2026-10-02T10:00:00Z" }, { id: "a1", version: 1, state: "scored", created_at: "2026-10-01T10:00:00Z" }];
    const m = html(<VersionHistory versions={versions} currentVersion={2} onSelect={() => undefined} comparable={[1]} />);
    expect(m).toContain('data-testid="compare-v1"');
    expect(m).not.toContain('data-testid="compare-v2"');
    expect(text(m)).toContain("v1, superseded");
    expect(text(m)).not.toMatch(/73\.7|100\.0/);
    expect(html(<VersionHistory versions={versions} currentVersion={2} />)).not.toContain("compare-v1");
  });
});
