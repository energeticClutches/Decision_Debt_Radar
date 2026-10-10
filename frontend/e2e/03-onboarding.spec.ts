import { expect, test } from "@playwright/test";

import { decisionByTitle, expectNoDdiNumber, loginAs, openTab, openWorkspace } from "./support";

const GATED_LABEL = "Gated Evidence Summary: not a validated decision artifact";

test.describe.serial("Onboarding: insufficient evidence, no DDI anywhere", () => {
  let id = "";
  test.beforeAll(async ({ request }) => {
    const d = await decisionByTitle(request, "onboarding redesign");
    id = d.id;
    expect(d.current_assessment?.state).toBe("insufficient_evidence");
  });

  test("the portfolio and every tab show no DDI number, band or contribution", async ({ page, request }) => {
    await loginAs(page, request, "pm2");
    await page.goto("/");
    const card = page.getByTestId(`decision-card-${id}`);
    await expect(card.getByTestId("headline")).toContainText("INSUFFICIENT EVIDENCE");
    await expect(card.locator("[data-ddi-value]")).toHaveCount(0);

    await openWorkspace(page, id);
    await expect(page.getByTestId("status-strip")).toHaveAttribute("data-kind", "gated");
    await expect(page.getByTestId("gate-card")).toBeVisible();
    await expect(page.getByTestId("gate-label")).toContainText("INSUFFICIENT EVIDENCE");
    await expect(page.getByTestId("ddi-card")).toHaveCount(0);
    const reasons = page.getByTestId("gate-reasons");
    await expect(reasons).toContainText("open_critical_dq");
    await expectNoDdiNumber(page);
    for (const tab of ["assessment", "evidence", "review", "traceability", "brief", "audit"]) {
      await openTab(page, tab);
      await expectNoDdiNumber(page);
    }
  });

  test("the assessment tab replaces the NBE reduction column by 'Resolves N blockers'", async ({ page, request }) => {
    await loginAs(page, request, "pm2");
    await openWorkspace(page, id, "assessment");
    await expect(page.getByTestId("nbe-table")).toHaveAttribute("data-gated", "true");
    await expect(page.getByTestId("nbe-reduction")).toHaveCount(0);
    await expect(page.getByTestId("nbe-reduction-head")).toHaveCount(0);
    await expect(page.getByTestId("nbe-resolves").first()).toHaveText(/^Resolves \d+ blockers?$/);
    await expect(page.getByTestId("why-score")).toHaveCount(0);
    await expect(page.getByTestId("dimension-table")).toHaveCount(0);
    await expect(page.getByTestId("gate-unblocking")).toBeVisible();
  });

  test("the Decision Brief action shows the server's 409 reason; the Gated Evidence Summary opens with its label", async ({ page, request }) => {
    await loginAs(page, request, "pm2");
    await openWorkspace(page, id, "brief");
    await page.getByTestId("create-decision-brief").click();
    const error = page.getByTestId("brief-error");
    await expect(error).toBeVisible();
    await expect(error).toContainText("only after the assessment is validated");
    await expect(page.getByTestId("brief-list-item")).toHaveCount(0);

    await page.getByTestId("create-gated-summary").click();
    await expect(page.getByTestId("brief-list-item")).toHaveCount(1);
    await page.getByTestId("brief-created").getByRole("link").click();
    await expect(page.getByTestId("brief")).toHaveAttribute("data-kind", "gated_evidence_summary");
    await expect(page.getByTestId("brief-label-top")).toHaveText(GATED_LABEL);
    await expect(page.getByTestId("brief-label-bottom")).toHaveText(GATED_LABEL);
    await expect(page.getByTestId("brief-gate-reasons")).toContainText("open_critical_dq");
    await expectNoDdiNumber(page);
  });

  test("a gated decision offers no version comparison and shows no contribution from an older version", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "assessment");
    await expect(page.getByTestId("version-history")).toBeVisible();
    await expect(page.locator('[data-testid^="compare-v"]')).toHaveCount(0);
    await expect(page.getByTestId("version-compare")).toHaveCount(0);
    await expectNoDdiNumber(page);
  });
});
