import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = "http://127.0.0.1:8000";
export const IDENTITY_KEY = "ddr.demo_user";
export const REPLAY_NOTICE = "Replayed demo fixture, not live model output";

export interface DemoUser { id: string; name: string; role: string }

export async function getUsers(request: APIRequestContext): Promise<DemoUser[]> {
  const res = await request.get(`${API}/users`);
  expect(res.ok()).toBeTruthy();
  return res.json();
}

export async function userByName(request: APIRequestContext, part: string): Promise<DemoUser> {
  const u = (await getUsers(request)).find((x) => x.name.includes(part));
  if (!u) throw new Error(`no demo user named like ${part}`);
  return u;
}

export const PERSONAS = { pm: "Priya", pm2: "Marcus", ba: "Elena", analyst: "Tom", leader: "Hannah", executive: "Rafael", bizops: "Sana" } as const;

/** Acts as a persona for the page (the demo role switcher stores the id in localStorage). */
export async function loginAs(page: Page, request: APIRequestContext, persona: keyof typeof PERSONAS): Promise<DemoUser> {
  const user = await userByName(request, PERSONAS[persona]);
  await page.addInitScript(([k, v]) => window.localStorage.setItem(k, v), [IDENTITY_KEY, user.id]);
  return user;
}

export async function switchTo(page: Page, request: APIRequestContext, persona: keyof typeof PERSONAS): Promise<void> {
  const user = await userByName(request, PERSONAS[persona]);
  await page.getByTestId("identity-select").selectOption(user.id);
}

export interface ApiDecision { id: string; title: string; lifecycle_stage: string; current_assessment: { id: string; state: string; ddi: number | null; band: string | null } | null }

export async function decisionByTitle(request: APIRequestContext, titlePart: string): Promise<ApiDecision> {
  const pm = await userByName(request, PERSONAS.pm);
  const res = await request.get(`${API}/decisions`, { headers: { "X-Demo-User": pm.id } });
  const d = ((await res.json()) as ApiDecision[]).find((x) => x.title.includes(titlePart));
  if (!d) throw new Error(`no decision titled like ${titlePart}`);
  return d;
}

export async function openWorkspace(page: Page, id: string, tab?: string): Promise<void> {
  await page.goto(`/decisions/${id}${tab ? `?tab=${tab}` : ""}`);
  await expect(page.getByTestId("workspace-title")).toBeVisible();
}

export async function openTab(page: Page, tab: string): Promise<void> {
  await page.getByTestId(`tab-${tab}`).click();
  await expect(page.getByTestId(`tab-panel-${tab}`)).toBeVisible();
}

/** No DDI number may appear in the DOM of a gated decision: no data-ddi-value and no "DDI <number>" pattern in the visible text. */
export async function expectNoDdiNumber(page: Page): Promise<void> {
  await expect(page.locator("[data-ddi-value]")).toHaveCount(0);
  const body = await page.locator("main").innerText();
  expect(body).not.toMatch(/\bDDI\b\s*[:=]?\s*\d/);
  expect(body).not.toMatch(/\b(low|moderate|high|critical)\s+band\b/i);
}
