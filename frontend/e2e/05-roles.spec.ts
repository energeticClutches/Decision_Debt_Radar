import { expect, test } from "@playwright/test";

import { API, decisionByTitle, loginAs, openWorkspace, PERSONAS, userByName } from "./support";

test.describe("Role checks", () => {
  test("a product analyst sees Validate disabled, naming the roles that can, and a forced call returns 403", async ({ page, request }) => {
    const d = await decisionByTitle(request, "onboarding redesign");
    await loginAs(page, request, "analyst");
    await openWorkspace(page, d.id, "review");
    await expect(page.getByTestId("validate-open")).toBeDisabled();
    await expect(page.getByTestId("validate-open-hint")).toContainText("Allowed roles:");
    await expect(page.getByTestId("validate-open-hint")).toContainText("Product Manager");
    await expect(page.getByTestId("next-action")).toBeDisabled();
    await expect(page.getByTestId("next-action-reason")).toContainText("Allowed roles:");
    const analyst = await userByName(request, PERSONAS.analyst);
    const res = await request.post(`${API}/decisions/${d.id}/validate`, { headers: { "X-Demo-User": analyst.id } });
    expect(res.status()).toBe(403);
    expect((await res.json()).error.detail.allowed_roles).toEqual(["dept_leader", "executive", "ba", "pm"].sort());
  });

  test("a product manager cannot approve customer evidence: the control is disabled and a forced call returns 403", async ({ page, request }) => {
    const d = await decisionByTitle(request, "premium subscription price");   // never decided by another spec
    // the prepared demo has no pending item, so the customer list is shown with one item turned into a proposal (a display-only mock)
    await page.route("**/api/decisions/*/customer-evidence", async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      body.items[0].evidence.status = "proposed";
      body.items[0].evidence.approved_by = null;
      await route.fulfill({ response: res, json: body });
    });
    await loginAs(page, request, "pm");
    await openWorkspace(page, d.id, "evidence");
    await page.getByTestId("evidence-sub-customer").click();
    const proposed = page.locator('[data-testid^="customer-card-"][data-status="proposed"]').first();
    await expect(proposed).toBeVisible();
    await expect(proposed.getByTestId("approval-warning")).toHaveText("Approval changes the evidence: the current assessment becomes stale. Rejection is permanent for this item.");
    await proposed.locator("textarea").fill("a note");
    await expect(proposed.locator('button[data-action="approve_evidence"]').first()).toBeDisabled();
    await expect(proposed).toContainText("Allowed roles: Business Analyst, Product Analyst");
    // a business analyst gets enabled controls once a note is written
    await page.getByTestId("identity-select").selectOption((await userByName(request, PERSONAS.ba)).id);
    await expect(proposed.locator('button[data-action="approve_evidence"]').first()).toBeEnabled();

    const items = await (await request.get(`${API}/decisions/${d.id}/customer-evidence`, { headers: { "X-Demo-User": (await userByName(request, PERSONAS.pm)).id } })).json();
    const pm = await userByName(request, PERSONAS.pm);
    const forced = await request.patch(`${API}/evidence/${items.items[0].evidence.id}/approval`, { headers: { "X-Demo-User": pm.id }, data: { action: "approve", note: "x" } });
    expect(forced.status()).toBe(403);
    expect((await forced.json()).error.detail.allowed_roles).toEqual(["ba", "product_analyst"]);
  });

  test("an executive can record the decision, a non-owner product manager cannot", async ({ page, request }) => {
    const d = await decisionByTitle(request, "community challenges");          // validated by the Community spec
    expect(d.lifecycle_stage).toBe("validated");
    // Marcus Webb is a product manager who does not own this decision (Priya Raman does)
    const marcus = await userByName(request, PERSONAS.pm2);
    await loginAs(page, request, "pm2");
    await openWorkspace(page, d.id, "brief");
    await page.getByTestId("record-rationale").fill("A rationale.");
    await expect(page.getByTestId("record-submit")).toBeDisabled();
    await expect(page.getByTestId("record-submit-hint")).toContainText("Allowed roles: Department Leader, Executive");
    const refused = await request.post(`${API}/decisions/${d.id}/decision-record`, {
      headers: { "X-Demo-User": marcus.id }, data: { outcome: "approve", rationale: "A rationale.", acknowledged_risk: true },
    });
    expect(refused.status()).toBe(403);

    await page.getByTestId("identity-select").selectOption((await userByName(request, PERSONAS.executive)).id);
    await expect(page.getByTestId("record-submit")).toBeEnabled();
    await page.getByTestId("record-ack").check();
    await page.getByTestId("record-submit").click();
    await expect(page.getByTestId("decided-lock")).toBeVisible();
    await expect(page.getByTestId("stepper")).toHaveAttribute("data-stage", "decided");
  });
});
