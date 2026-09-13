import { expect, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ASSETS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../presentation/assets/screens");

export const ROLES = {
  MINISTRY: { email: "ministry@demo", slug: "ministry" },
  STATE: { email: "state.up@demo", slug: "state" },
  DISTRICT: { email: "district.lucknow@demo", slug: "district" },
  MP: { email: "mp.0147@demo", slug: "mp" },
} as const;
export type RoleName = keyof typeof ROLES;

export interface PageSpec {
  path: string;
  name: string;
  /** A selector that only appears once the page has real data. */
  ready: string;
  reviewersOnly?: boolean;
}

export const PAGES: PageSpec[] = [
  { path: "/", name: "command-centre", ready: '[data-testid="kpis"]' },
  { path: "/map", name: "risk-map", ready: '[data-testid="map-coverage"]:has-text("works")' },
  { path: "/money", name: "money-at-risk", ready: '[data-testid="money-treemap"], [data-testid="empty-state"]' },
  { path: "/alerts", name: "alerts-inbox", ready: '[data-testid="alerts-total"]:has-text("of")' },
  { path: "/cases", name: "cases", ready: '[data-testid="case-list"], [data-testid="empty-state"]', reviewersOnly: true },
  { path: "/duplicates", name: "duplicate-finder", ready: '[data-testid="pairs-total"]:has-text("of")' },
  { path: "/network", name: "vendor-network", ready: '[data-testid="benford"]' },
  { path: "/delays", name: "delays", ready: '[data-testid="delay-table"], [data-testid="empty-state"]' },
  { path: "/compliance", name: "compliance", ready: '[data-testid="rules-heatmap"], [data-testid="empty-state"]' },
  { path: "/trends", name: "trends", ready: '[data-testid="cost-distribution"], [data-testid="empty-state"]' },
  { path: "/portfolio", name: "mp-portfolio", ready: '[data-testid="portfolio-framing"]' },
  { path: "/models", name: "model-performance", ready: '[data-testid="detector-table"]' },
  { path: "/simulator", name: "threshold-simulator", ready: '[data-testid="sim-results"]:has-text("was")', reviewersOnly: true },
  { path: "/learning", name: "learning", ready: '[data-testid="learning-channels"], [data-testid="empty-state"]', reviewersOnly: true },
  { path: "/ingest", name: "data-ingest", ready: '[data-testid="dropzone"]', reviewersOnly: true },
];

/** Collect console errors and uncaught exceptions for the life of the page. */
export function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

export async function login(page: Page, role: RoleName): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ROLES[role].email);
  await page.getByLabel("Password").fill("demo123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByTestId("scope-chip")).toBeVisible();
}

export async function token(page: Page): Promise<string> {
  const value = await page.evaluate(() => localStorage.getItem("sentinel.token"));
  if (!value) throw new Error("no token after login");
  return value;
}

export async function apiGet<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(`http://127.0.0.1:8000/api${path}`, {
    headers: { Authorization: `Bearer ${await token(page)}` },
  });
  expect(response.status(), path).toBe(200);
  return (await response.json()) as T;
}

export async function settle(page: Page, ready: string): Promise<void> {
  await page.locator(ready).first().waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700);
  await expect(page.getByText("This view could not load")).toHaveCount(0);
}

export async function shoot(page: Page, name: string, fullPage = true): Promise<void> {
  await page.screenshot({ path: path.join(ASSETS, `${name}.png`), fullPage, animations: "disabled" });
}

export const indian = (n: number) => new Intl.NumberFormat("en-IN").format(n);
