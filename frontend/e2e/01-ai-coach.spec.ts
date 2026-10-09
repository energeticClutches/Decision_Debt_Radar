import { expect, test } from "@playwright/test";

import { API, decisionByTitle, loginAs, openTab, openWorkspace, REPLAY_NOTICE, switchTo, userByName, PERSONAS } from "./support";

// AI Coach: the full path to `decided`. State carries over between the steps (serial), and the run needs a fresh demo state.
test.describe.serial("AI Coach: the full path to decided", () => {
  let id = "";
  let ddi = 0;
  let band = "";

  test.beforeAll(async ({ request }) => {
    const d = await decisionByTitle(request, "AI Coach");
    id = d.id;
    expect(d.lifecycle_stage).toBe("challenged");
    ddi = d.current_assessment?.ddi as number;
    band = d.current_assessment?.band as string;
  });

  test("the portfolio headline is the engine's DDI and band, and the header says what this is", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await page.goto("/");
    const card = page.getByTestId(`decision-card-${id}`);
    await expect(card).toBeVisible();
    await expect(card.getByTestId("headline")).toHaveText(`DDI ${ddi.toFixed(1)} · ${band.charAt(0).toUpperCase()}${band.slice(1)}`);
    await expect(card).toHaveAttribute("data-headline", "scored");
    await expect(page.getByTestId("auth-disclaimer")).toContainText("Demo identity only: not authentication");
    await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data");
    await expect(page.getByTestId("llm-chip")).toBeVisible();
  });

  test("the review shows the blocking finding, the replay notice and a disabled Validate", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "review");
    await expect(page.getByTestId("status-strip")).toHaveAttribute("data-kind", "needs_rework");
    await expect(page.getByTestId("synthesis-header")).toContainText("AI-generated interpretation · validated by code checks · version 1");
    await expect(page.getByTestId("synthesis-header").getByTestId("provenance-notice")).toHaveText(REPLAY_NOTICE);
    const blocking = page.locator('[data-testid="finding-blocking"][data-category="causal_from_observational"]');
    await expect(blocking).toBeVisible();
    await expect(blocking.getByTestId("finding-source")).toHaveText("Reviewer");
    await expect(page.getByTestId("reviewer-copy")).toHaveText("Verdict derived by code from finding severities.");
    await expect(page.getByTestId("validate-open")).toBeDisabled();
    await expect(page.getByTestId("next-action")).toHaveText("Resolve review findings");
    // a claim chip opens the claim drawer; unknown ids would stay plain text
    await page.getByTestId("claim-chip-c1").first().click();
    await expect(page.getByTestId("drawer-claim")).toBeVisible();
    await page.getByTestId("drawer-close").click();
  });

  test("a person overrides the verdict with a reason, then validates the assessment (not the decision)", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "review");
    const override = page.getByTestId("rework-override");
    await expect(override).toBeDisabled();                                         // a reason is mandatory
    await page.getByTestId("override-reason").fill("Reviewed by hand: claim c7 is reclassified as associative, not causal.");
    await expect(override).toBeEnabled();
    await override.click();
    await expect(page.getByTestId("human-reviews")).toContainText("claim c7 is reclassified");
    await expect(page.getByTestId("status-strip")).not.toHaveAttribute("data-kind", "needs_rework");
    await expect(page.getByTestId("next-action")).toHaveText("Validate the assessment");
    await page.getByTestId("validate-open").click();
    const dialog = page.getByTestId("validate-dialog");
    await expect(dialog).toContainText("I understand this validates the evidence assessment, not the decision.");
    await expect(page.getByTestId("validate-confirm")).toBeDisabled();
    await page.getByTestId("validate-checkbox").check();
    await page.getByTestId("validate-confirm").click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("stepper")).toHaveAttribute("data-stage", "validated");
    const badge = page.getByTestId("validated-badge");
    await expect(badge).toContainText("Assessment validated by review");
    await expect(badge).toContainText("The evidence assessment passed review. This does not mean the decision is correct.");
  });

  test("a Decision Brief is created and rendered from the stored content, without a recommendation", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "brief");
    await page.getByTestId("create-decision-brief").click();
    const link = page.getByTestId("brief-created").getByRole("link");
    await expect(link).toBeVisible();
    await expect(page.getByTestId("brief-list-item")).toHaveCount(1);
    await link.click();
    await expect(page.getByTestId("brief")).toHaveAttribute("data-kind", "decision_brief");
    await expect(page.getByTestId("brief-label-top")).toHaveText("Validated Decision Brief");
    await expect(page.getByTestId("brief-synthetic")).toContainText("Synthetic data");
    await expect(page.getByTestId("provenance-notice")).toHaveText(REPLAY_NOTICE);
    await expect(page.getByTestId("brief-ddi").locator("[data-ddi-value]")).toHaveCount(1);
    for (const section of ["brief-decision", "brief-evidence-says", "brief-supporting-contradicting", "brief-uncertainty", "brief-ddi", "brief-dq", "brief-nbe", "brief-review", "brief-criteria", "brief-record", "brief-traceability"]) {
      await expect(page.getByTestId(section)).toBeVisible();
    }
    expect(await page.getByTestId("brief").innerText()).not.toMatch(/recommend/i);
    await expect(page.getByTestId("brief-markdown")).toHaveAttribute("download", /\.md$/);
    expect(await page.locator("script", { hasText: "alert(" }).count()).toBe(0);
  });

  test("an executive records the decision, and then every write control is disabled", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "brief");
    await switchTo(page, request, "executive");
    await page.getByTestId("record-rationale").fill("Proceed with conditions: re-run the holdout with a fixed allocation first.");
    await page.getByTestId("record-ack").check();
    await expect(page.getByTestId("record-submit")).toBeEnabled();
    await page.getByTestId("record-submit").click();
    await expect(page.getByTestId("decided-lock")).toHaveText("Decision recorded. Writes are frozen.");
    await expect(page.getByTestId("status-strip")).toHaveAttribute("data-kind", "decided");
    await expect(page.getByTestId("status-strip")).toContainText("Decision recorded. Writes are frozen.");
    await expect(page.getByTestId("next-action-none")).toBeVisible();
    await expect(page.getByTestId("record-existing")).toContainText("Proceed with conditions");
    await expect(page.getByTestId("create-decision-brief")).toBeDisabled();
    await expect(page.getByTestId("create-gated-summary")).toBeDisabled();

    await openTab(page, "canvas");
    await expect(page.getByTestId("canvas-edit")).toBeDisabled();
    await expect(page.getByTestId("canvas-readonly")).toBeVisible();

    await openTab(page, "review");
    await expect(page.getByTestId("resynthesise")).toBeDisabled();
    await expect(page.getByTestId("validate-open")).toBeDisabled();
    await expect(page.getByTestId("human-review-ready")).toBeDisabled();

    await openTab(page, "evidence");
    await page.getByTestId("evidence-sub-dq").click();
    // the server refuses writes too
    const pm = await userByName(request, PERSONAS.pm);
    const refused = await request.patch(`${API}/decisions/${id}/canvas`, { headers: { "X-Demo-User": pm.id }, data: { title: "Changed after the decision" } });
    expect(refused.status()).toBe(409);
  });
});
