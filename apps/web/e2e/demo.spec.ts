import { expect, test, type Page } from "@playwright/test";

const API = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";
const SHOTS = "test-results/screens";

function trackConsole(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test.describe.serial("ATLAS Day 1-3 walkthrough", () => {
  test("app boots and backend is healthy", async ({ page, request }) => {
    const health = await (await request.get(`${API}/health`)).json();
    expect(health.database).toBe(true);
    const errors = trackConsole(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByText("DEMO MODE · SIMULATED SIGNALS")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("reset, then run Day 1, Day 2, Day 3 from the UI", async ({ page }) => {
    const errors = trackConsole(page);
    await page.goto("/");
    await page.getByTestId("reset").click();
    await page.getByTestId("confirm-reset").click();
    await expect(page.getByText("Demo reset.")).toBeVisible();
    for (const day of [1, 2, 3]) {
      const card = page.getByTestId(`day-card-${day}`);
      await page.getByTestId(`run-day-${day}`).click();
      await expect(card.getByText("COMPLETED")).toBeVisible({ timeout: 120_000 });
      await expect(card.getByText(/new pages/)).toContainText(/[2-9] new pages/);
    }
    await page.screenshot({ path: `${SHOTS}/01-overview.png`, fullPage: true });
    expect(errors).toEqual([]);
  });

  test("6+ unique articles in EN / HI / Hinglish, red-team draft blocked", async ({ page, request }) => {
    const errors = trackConsole(page);
    await page.goto("/content");
    await expect(page.getByTestId("article-card").first()).toBeVisible();
    const arts = await (await request.get(`${API}/api/v1/articles?origin=GENERATED`)).json();
    const real = arts.filter((a: any) => !a.is_test_fixture);
    expect(real.length).toBeGreaterThanOrEqual(6);
    expect(new Set(real.map((a: any) => a.intent_key)).size).toBe(real.length);
    expect(new Set(real.map((a: any) => a.language))).toEqual(new Set(["en", "hi", "hi-Latn"]));
    const red = arts.find((a: any) => a.is_test_fixture);
    expect(red.compliance_status).toBe("BLOCK");
    await expect(page.getByText("RED-TEAM FIXTURE")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/02-content.png`, fullPage: true });
    expect(errors).toEqual([]);
  });

  test("article page renders with evidence and compliance", async ({ page, request }) => {
    const errors = trackConsole(page);
    const arts = await (await request.get(`${API}/api/v1/articles?origin=GENERATED&include_test=false`)).json();
    const hindi = arts.find((a: any) => a.language === "hi");
    await page.goto(`/content/${hindi.id}`);
    await expect(page.getByTestId("article-preview").locator("h1")).toBeVisible();
    await expect(page.getByTestId("article-preview")).toContainText("जोखिम चेतावनी");
    await page.screenshot({ path: `${SHOTS}/03-article-hindi.png`, fullPage: true });
    await page.getByRole("tab", { name: "Evidence & sources" }).click();
    await expect(page.getByTestId("evidence-panel")).toContainText("Reserve Bank of India");
    await page.screenshot({ path: `${SHOTS}/04-evidence.png`, fullPage: true });
    await page.getByRole("tab", { name: "Compliance" }).click();
    await expect(page.getByTestId("rule-checklist")).toBeVisible();
    await page.getByRole("tab", { name: "SEO & schema" }).click();
    await expect(page.getByText("FAQPage").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/05-seo.png`, fullPage: true });
    expect(errors).toEqual([]);
  });

  test("blocked red-team article shows violations", async ({ page, request }) => {
    const arts = await (await request.get(`${API}/api/v1/articles`)).json();
    const red = arts.find((a: any) => a.is_test_fixture);
    await page.goto(`/content/${red.id}`);
    await expect(page.getByText("ADVERSARIAL TEST FIXTURE.")).toBeVisible();
    await page.getByRole("tab", { name: "Compliance" }).click();
    await expect(page.getByTestId("rule-checklist")).toContainText("Prohibited claims");
    await page.screenshot({ path: `${SHOTS}/06-redteam-blocked.png`, fullPage: true });
  });

  test("opportunities show duplicate rejection with explainable scores", async ({ page }) => {
    const errors = trackConsole(page);
    await page.goto("/opportunities");
    await expect(page.getByTestId("opportunity-row").first()).toBeVisible();
    await expect(page.getByText("UPDATE EXISTING").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/07-opportunities.png`, fullPage: true });
    await page.getByTestId("opportunity-row").first().getByRole("link").first().click();
    await expect(page.getByTestId("score-breakdown")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/08-opportunity-detail.png`, fullPage: true });
    expect(errors).toEqual([]);
  });

  test("ledger lists articles and CSV export works", async ({ page, request }) => {
    await page.goto("/ledger");
    await expect(page.getByTestId("ledger-row").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/09-ledger.png`, fullPage: true });
    const csv = await request.get(`${API}/api/v1/ledger/export`);
    expect(csv.status()).toBe(200);
    const text = await csv.text();
    expect(text.split("\n").filter((l) => l.includes("ARTICLE_CREATED")).length).toBeGreaterThanOrEqual(6);
  });

  test("compliance sandbox blocks unsafe text; workflows history visible", async ({ page }) => {
    await page.goto("/compliance");
    await page.getByRole("tab", { name: "Policy sandbox" }).click();
    await page.getByTestId("sandbox-run").click();
    await expect(page.getByTestId("sandbox-result")).toContainText("BLOCK");
    await page.screenshot({ path: `${SHOTS}/10-compliance-sandbox.png`, fullPage: true });
    await page.goto("/workflows");
    await expect(page.getByTestId("run-row").first()).toBeVisible();
    await page.getByTestId("run-row").first().getByRole("link").first().click();
    await expect(page.getByText("Pipeline steps")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/11-workflow-run.png`, fullPage: true });
  });

  test("all pages render without console errors (incl. mobile width)", async ({ page }) => {
    const errors = trackConsole(page);
    for (const path of ["/", "/search", "/opportunities", "/content", "/workflows", "/compliance", "/ledger", "/playbook", "/settings"]) {
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator("main h1")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(overflow).toBe(false);
    await page.screenshot({ path: `${SHOTS}/12-mobile.png`, fullPage: true });
    expect(errors).toEqual([]);
  });
});
