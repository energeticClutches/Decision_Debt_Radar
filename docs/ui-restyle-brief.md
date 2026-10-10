# UI Restyle Brief: apply the Stitch design system (look only)

**Status:** APPROVED by the PO (2026-10-10). **Source:** `design/stitch/` (`DESIGN.md` = tokens and component rules, `screen.png` = target look, `code.html` = reference markup). **Baseline:** commit `1850181`.

> Copy the **theme and UI/UX** of the Stitch design. Do **not** copy its sample content or features. The backend, API, data, behaviour, wording and trust rules stay exactly as they are.

## 1. Scope

**May change:**
- `frontend/app/globals.css`, every `*.module.css`;
- the JSX **markup, classes and layout** of `frontend/components/**` and `frontend/app/**`;
- a new `frontend/components/icons.tsx` (inline SVG icons, no library);
- `frontend/app/layout.tsx` (load Inter with `next/font/google`, which is self-hosted at build time and not a runtime dependency).

**Must NOT change:**
- `frontend/lib/**` (API client, `actions.ts`, `claims.ts`, `format.ts`, types, `useResource`) and any data flow or fetch logic in `Workspace.tsx`, including the loading-trust gate;
- everything under `backend/`, `database/`, `scripts/`, `tests/` (pytest);
- no new runtime dependencies, no Tailwind, no CDN links (no Google Fonts `<link>`, no Material Symbols), no chart library, no Markdown or HTML renderer, no `dangerouslySetInnerHTML`.

## 2. What to copy from Stitch (visual system)

- **Tokens.** Put them on `:root` (light) with a matching dark theme under `prefers-color-scheme: dark` and `[data-theme="dark"]`:
  - canvas `#f8fafc`, surface `#ffffff`, sub-surface `#f1f5f9`;
  - borders `#e2e8f0` and `#cbd5e1`;
  - text `#0f172a`, `#475569` and `#94a3b8`;
  - primary `#2563eb` (hover `#1d4ed8`, tint `#eff6ff`);
  - alerts: warning amber, blocker rose, info sky, resolved emerald (`DESIGN.md` §Operational Alerts);
  - **debt bands** low `#94a3b8`, moderate `#64748b`, high `#6366f1`, critical `#4338ca`, with badge styles from `DESIGN.md` §Chips. **Never red/green for debt.**
- **Type.**
  - Inter throughout.
  - `font-variant-numeric: tabular-nums` on every number, table and metric.
  - Uppercase micro-labels (11 px, 600, +0.06em) for section kickers and table headers.
  - Card titles 16 px/600; the decision title 24 px/600; the DDI number about 44 px/600.
- **Top bar (as in `screen.png`):**
  - logo mark and product name;
  - the "Synthetic data" and "Demo mode: replayed fixtures" micro-badges;
  - on the right, the "Demo identity only: not authentication" kicker and the "Acting as" persona select;
  - **on workspace pages, the workspace tabs sit in this bar as underline tabs** (active tab dark with a 2 px blue underline). The tabs keep their `role="tab"`, keyboard behaviour and `data-testid`s.
- **Decision header card:**
  - the title and meta line (owner and team);
  - the hypothesis in a tinted callout with an icon;
  - **the stepper as connected nodes** (completed: blue filled with a check; current: filled blue pill; upcoming: grey numbered), joined by a 2 px rail (`DESIGN.md` §Stepper);
  - the status strip as a **3 px left-spine alert banner**;
  - one primary button top-right (the existing next action, unchanged logic).
- **Cards:** white, hairline border, Level-1 shadow, 12 px radius, 24 px padding, an uppercase kicker title with a small icon, 16–24 px gaps on a 12-column grid.
- **DDI card:** the big number plus a band badge; the existing caption line in a sub-surface callout; the existing sensitivity and as-of footer. **Style only what already exists.**
- **Direction card:** the existing label as a headline. Supporting and contradicting shares as a thin split bar plus small stat tiles (supports / contradicts / items), **using only the values the API already returns** (shares, item count, threshold).
- **Tables:**
  - 36 px header in sub-surface with uppercase micro-labels;
  - 48 px rows with hover;
  - numbers right-aligned and tabular;
  - claim and evidence chips as small mono pills;
  - long text clamped with `title`.
- **Chips:** categorical labels as 4 px micro-rectangles; state badges as pills. Always text and/or an icon, never colour alone.
- **Buttons:** primary, secondary, ghost and destructive per `DESIGN.md`, 36 px tall, 6 px radius, visible focus ring (`2px rgba(37,99,235,.15)` plus a border).
- **Dialogs and drawers:** Level-3 shadow, slate backdrop with blur.
- **AI-generated panel:** a tinted panel with one "AI-generated interpretation" kicker and the replay note, as in the Review summary of `screen.png`.

## 3. Do NOT copy (Stitch sample content that conflicts with the product)

Do not add:
- breadcrumbs with fake IDs, version tags, "Changelog", "Ledger Audit Synchronized", "Export Brief" or "Submit for Re-evaluation";
- "Upper limit: 100.0", "Historical median", "Evidence Coverage / Rigor Gap / Telemetry Decay" bars, "net balance" numbers, "Rigor Score", "Assign" or "Log Evidence" buttons, "Queue sort";
- "Evaluated against …", "Synthesized from N verified claims", footer version strings.

Show only data the API returns, with the existing wording.

## 4. Invariants (tests enforce most of these)

- **Every existing `data-testid` and every exact copy string stays.** These include the stale banner, the DDI caption, "Direction is separate from DDI.", "Set by taxonomy, not by AI", the synthesis header, "Verdict derived by code from finding severities.", "No automated adversarial review", the validated badge text, the validate checkbox text, and "Decision recorded. Writes are frozen.".
- **Trust rules:**
  - a gated decision shows no DDI number, band, bar or contribution anywhere;
  - a stale DDI is greyed out and labelled STALE;
  - a superseded score appears only as "vN, superseded";
  - nothing claims "no review" or "no NBE" while loading.
- **The printable brief** (`/briefs/[briefId]`) keeps its print styles.
- **Accessibility:** AA contrast in both themes; status never conveyed by colour alone; focus visible; responsive down to 375 px with no horizontal page scroll (wide tables scroll inside their card).

## 5. Gate

Run in order:
1. `tsc --noEmit`;
2. Vitest;
3. `next build`;
4. Playwright: **all 20** tests plus the screenshot spec (`SCREENSHOTS=1`). Regenerate `docs/screenshots/*.png`.
5. `git diff --stat 1850181 -- frontend/lib backend database scripts tests`: empty.

Then restore the demo state with `scripts/demo_prepare.py --reset`. Do not commit.
