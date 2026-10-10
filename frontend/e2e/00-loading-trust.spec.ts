import { expect, test } from "@playwright/test";

import { decisionByTitle, loginAs } from "./support";

// Trust rule found at Day-7 verification: while the reviews and NBE of the current assessment are still loading, the workspace must
// never claim "No automated adversarial review" or "No next-best-evidence action". A MutationObserver installed before any script
// runs records whether either claim was EVER in the DOM, from the first paint to the settled page. Runs first, on the prepared state.
const CLAIMS = ["No automated adversarial review", "No next-best-evidence action is listed"];

test("a decision with a review and NBE actions never shows 'no review' or 'no NBE', not even while loading", async ({ page, request }) => {
  const d = await decisionByTitle(request, "AI Coach");
  expect(d.lifecycle_stage).toBe("challenged");
  await loginAs(page, request, "pm");
  await page.addInitScript((claims) => {
    const w = window as unknown as { __seenClaims: string[] };
    w.__seenClaims = [];
    const check = () => {
      const text = document.body?.innerText ?? "";
      for (const c of claims) if (text.includes(c) && !w.__seenClaims.includes(c)) w.__seenClaims.push(c);
    };
    new MutationObserver(check).observe(document, { childList: true, subtree: true, characterData: true });
  }, CLAIMS);
  await page.goto(`/decisions/${d.id}?tab=overview`);
  await expect(page.getByTestId("workspace")).toBeVisible();
  await expect(page.getByText("Verdict derived by code from finding severities.").first()).toBeVisible();
  const seen = await page.evaluate(() => (window as unknown as { __seenClaims: string[] }).__seenClaims);
  expect(seen).toEqual([]);
});
