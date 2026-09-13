import { expect, test } from "@playwright/test";
import { apiGet, indian, login, PAGES, ROLES, settle, shoot, watchConsole, type RoleName } from "./helpers";

interface Overview {
  kpis: { works: number };
  scope: string;
}
interface AlertPage {
  total: number;
  items: { alert_id: string; state: string; district: string }[];
}

test.beforeAll(async ({ request }) => {
  // Screenshots are committed to a public repository: refuse to run without pseudonyms.
  const health = await request.get("http://127.0.0.1:8000/api/health");
  expect((await health.json()).presentation_mode, "API must run with PRESENTATION_MODE=1").toBe(true);
});

let ministryWorks = 0;

for (const role of Object.keys(ROLES) as RoleName[]) {
  test.describe(`${role} role`, () => {
    test(`visits every page without console errors`, async ({ page }) => {
      const errors = watchConsole(page);
      await login(page, role);
      const overview = await apiGet<Overview>(page, "/overview");
      if (role === "MINISTRY") ministryWorks = overview.kpis.works;

      for (const [index, spec] of PAGES.entries()) {
        await page.goto(spec.path);
        if (spec.reviewersOnly && role === "MP") {
          // MPs do not review, upload or tune: the route sends them home and the nav hides it.
          await expect(page).toHaveURL(/\/$/);
          await expect(page.locator(`nav a[href="${spec.path}"]`)).toHaveCount(0);
          continue;
        }
        if (spec.name === "mp-portfolio" && role !== "MP") {
          await page.getByTestId("constituency-select").waitFor();
          const firstOption = page.getByTestId("constituency-select").locator("option").nth(1);
          await page.getByTestId("constituency-select").selectOption(await firstOption.getAttribute("value") ?? "");
          await page.getByTestId("portfolio-title").waitFor();
        }
        await settle(page, spec.ready);
        const full = role === "MINISTRY" || ["command-centre", "alerts-inbox", "mp-portfolio", "risk-map"].includes(spec.name);
        if (full) await shoot(page, `${ROLES[role].slug}-${String(index + 1).padStart(2, "0")}-${spec.name}`);
      }

      // The Works KPI is the scoped API figure, formatted, not a number typed into the UI.
      await page.goto("/");
      await settle(page, '[data-testid="kpis"]');
      await expect(page.getByTestId("kpis")).toContainText(indian(overview.kpis.works));

      expect(errors, errors.join("\n")).toEqual([]);
    });
  });
}

test.describe("scoping", () => {
  test("state officer sees only Uttar Pradesh", async ({ page }) => {
    await login(page, "STATE");
    const alerts = await apiGet<AlertPage>(page, "/alerts?limit=200");
    expect(alerts.items.length).toBeGreaterThan(0);
    expect(alerts.items.every((a) => a.state === "Uttar Pradesh")).toBe(true);
    const overview = await apiGet<Overview>(page, "/overview");
    expect(ministryWorks === 0 || overview.kpis.works < ministryWorks).toBe(true);

    await page.goto("/alerts");
    await settle(page, '[data-testid="alerts-total"]:has-text("of")');
    const rows = page.getByTestId("alert-list").getByRole("option");
    const texts = await rows.allInnerTexts();
    expect(texts.length).toBeGreaterThan(0);
    for (const text of texts) expect(text).toContain("Uttar Pradesh");
  });

  test("district officer sees only Lucknow and cannot open other districts", async ({ page }) => {
    const errors = watchConsole(page);
    await login(page, "DISTRICT");
    const alerts = await apiGet<AlertPage>(page, "/alerts?limit=200");
    expect(alerts.items.every((a) => a.district === "LUCKNOW")).toBe(true);

    await page.goto("/alerts");
    await settle(page, '[data-testid="alerts-total"]:has-text("of")');
    for (const text of await page.getByTestId("alert-list").getByRole("option").allInnerTexts()) {
      expect(text).toContain("LUCKNOW");
    }

    // A work outside the district is reported as not found, never shown.
    const outside = await page.request.get("http://127.0.0.1:8000/api/works?limit=1&state=Karnataka", {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("sentinel.token"))}` },
    });
    expect((await outside.json()).total).toBe(0);
    await page.goto("/works/WS/MP092/2026-2027/305015");
    await expect(page.getByText("This view could not load")).toBeVisible();
    await expect(page.getByText(/not found/i)).toBeVisible();
    // The 404 for the forbidden work is the only console error allowed here.
    expect(errors.filter((e) => !e.includes("404"))).toEqual([]);
  });

  test("MP sees their own constituency as implementation risk, and no reviewer tools", async ({ page }) => {
    await login(page, "MP");
    await page.goto("/portfolio");
    await settle(page, '[data-testid="portfolio-title"]');
    await expect(page.getByTestId("constituency-select")).toHaveCount(0);
    await expect(page.locator("main").getByText(/· MP code 147$/)).toBeVisible();
    await expect(page.getByTestId("portfolio-framing")).toContainText("not a judgement of the Member");

    const other = await page.request.get("http://127.0.0.1:8000/api/portfolio?mp_code=900", {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("sentinel.token"))}` },
    });
    expect(other.status()).toBe(404);
    await page.goto("/ingest");
    await expect(page).toHaveURL(/\/$/);
  });
});

test.describe("phase D", () => {
  test("threshold simulator moves the queue and resets to the configured weights", async ({ page }) => {
    const errors = watchConsole(page);
    await login(page, "MINISTRY");
    await page.goto("/simulator");
    const results = page.getByTestId("sim-results");
    await expect(results).toContainText("was");
    await expect(results).toContainText("±0");

    const rule = page.getByRole("slider", { name: "Rule layer" });
    await rule.focus();
    await page.keyboard.press("PageUp");
    await page.keyboard.press("PageUp");
    await expect(page.getByTestId("sim-reset")).toBeEnabled();
    await expect(results).not.toContainText("±0 · was", { timeout: 30_000 });
    await page.waitForLoadState("networkidle");
    await shoot(page, "ministry-38-simulator-changed", false);

    await page.getByTestId("sim-reset").click();
    await expect(page.getByTestId("sim-reset")).toBeDisabled();
    await expect(results).toContainText("±0", { timeout: 30_000 });
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("citizen view needs no login and shows no per-work risk", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/public");
    await page.getByTestId("citizen-districts").getByRole("button").first().waitFor();
    await page.getByTestId("citizen-districts").getByRole("button").first().click();
    await page.getByTestId("citizen-district").waitFor();
    await page.waitForLoadState("networkidle");
    // No band labels, scores or work ids anywhere on the page.
    const text = await page.locator("body").innerText();
    for (const forbidden of ["Critical", "High-risk", "risk score", "WS/MP"]) {
      expect(text.includes(forbidden), forbidden).toBe(false);
    }
    await shoot(page, "public-01-citizen-view", false);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("learning panel states its caveat and cases open a brief-ready case", async ({ page }) => {
    await login(page, "MINISTRY");
    await page.goto("/learning");
    await expect(page.getByTestId("learning-caveat")).toContainText("not precision in the field");
    await page.goto("/cases");
    await settle(page, '[data-testid="case-list"], [data-testid="empty-state"]');
    if (await page.getByTestId("case-list").count()) {
      await page.getByTestId("case-list").getByRole("button").first().click();
      await page.getByTestId("case-detail").waitFor();
      await page.waitForLoadState("networkidle");
      await shoot(page, "ministry-39-case-detail", false);
    }
  });
});

test.describe("resilience", () => {
  test("a failing API shows a designed error, retries, and recovers", async ({ page }) => {
    await login(page, "MINISTRY");
    // Break the overview endpoint and the health check.
    await page.route("**/api/overview", (route) => route.fulfill({ status: 503, body: JSON.stringify({ detail: "Service briefly unavailable" }), contentType: "application/json" }));
    await page.route("**/api/health", (route) => route.abort("connectionrefused"));
    await page.goto("/");
    await expect(page.getByText("This view could not load")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("api-down")).toBeVisible({ timeout: 45_000 });
    await shoot(page, "resilience-01-api-error", false);

    await page.unroute("**/api/overview");
    await page.unroute("**/api/health");
    await page.locator("main").getByRole("button", { name: "Try again" }).first().click();
    await expect(page.getByTestId("kpis")).toBeVisible({ timeout: 45_000 });
    await page.getByTestId("api-down").getByRole("button").click();
    await expect(page.getByTestId("api-down")).toHaveCount(0, { timeout: 30_000 });
  });

  test("unknown routes and an expired session are handled", async ({ page }) => {
    await login(page, "MINISTRY");
    await page.goto("/no-such-page");
    await expect(page.getByText("Page not found")).toBeVisible();
    // A token the server rejects signs the user out instead of looping.
    await page.evaluate(() => localStorage.setItem("sentinel.token", "not-a-valid-token"));
    await page.goto("/alerts");
    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
  });
});

test.describe("ministry walkthrough shots", () => {
  test("login, drawer, work detail, keyboard triage, Hindi and light theme", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/login");
    await page.getByText("Risk indicators for review of MPLADS works").waitFor();
    await page.waitForTimeout(600);
    await shoot(page, "ministry-00-login", false);

    await login(page, "MINISTRY");
    await page.goto("/alerts");
    await settle(page, '[data-testid="alerts-total"]:has-text("of")');
    // Keyboard triage: j moves down, e opens the drawer on the selected alert.
    await page.keyboard.press("j");
    await expect(page.getByTestId("alert-list").getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("e");
    await expect(page.getByTestId("alert-drawer")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("alert-drawer")).toHaveCount(0);

    // The Bhatpara CCTV alert, a seeded demo case.
    await page.goto(`/alerts?id=${encodeURIComponent("WS/MP18249/2025-2026/187617")}`);
    await page.getByTestId("suggested-action").waitFor();
    await page.waitForTimeout(600);
    await shoot(page, "ministry-30-alert-drawer", false);
    await page.getByRole("tab", { name: "Signals" }).click();
    await page.getByTestId("signal-bars").waitFor();
    await shoot(page, "ministry-31-alert-signals", false);
    await page.getByRole("tab", { name: "Peers" }).click();
    await page.getByTestId("peer-chart").waitFor();
    await shoot(page, "ministry-32-alert-peers", false);

    await page.goto("/works/WS/MP18249/2025-2026/187617");
    await settle(page, '[data-testid="work-title"]');
    await shoot(page, "ministry-33-work-detail");

    await page.goto("/duplicates?tab=splits");
    await page.getByTestId("split-weakness").waitFor();
    await shoot(page, "ministry-34-split-groups", false);

    // "What would clear this" on the top alert.
    await page.goto(`/alerts?id=${encodeURIComponent("WS/MP092/2026-2027/305015")}`);
    await page.getByRole("tab", { name: "What would clear this" }).click();
    await page.getByTestId("what-would-clear").waitFor();
    await page.waitForTimeout(500);
    await shoot(page, "ministry-37-what-would-clear", false);

    // Hindi. Go home first: the alert drawer would cover the header buttons.
    await page.goto("/");
    await settle(page, '[data-testid="kpis"]');
    await page.getByRole("button", { name: "Switch language" }).click();
    await expect(page.getByRole("heading", { name: "कमांड सेंटर" })).toBeVisible();
    await shoot(page, "ministry-35-command-centre-hindi", false);
    await page.getByRole("button", { name: "Switch language" }).click();

    // Light theme.
    await page.getByRole("button", { name: "Toggle theme" }).click();
    await page.goto("/");
    await settle(page, '[data-testid="kpis"]');
    await shoot(page, "ministry-36-command-centre-light", false);
    await page.getByRole("button", { name: "Toggle theme" }).click();

    expect(errors, errors.join("\n")).toEqual([]);
  });
});
