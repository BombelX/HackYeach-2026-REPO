import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";

async function enter(page: Page, telemetry = false) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your finances." }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: /Sign in/ })
    .first()
    .click();
  if (telemetry) await page.getByLabel(/Help improve the demo/).check();
  await page.getByLabel("Login", { exact: true }).fill("anna.demo");
  await page.getByLabel("Password", { exact: true }).fill("bank24");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Confirmation code", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Confirm sign-in" }).click();
  await expect(
    page.getByRole("heading", { name: "Hello" }),
  ).toBeVisible();
}
async function prepare(page: Page, amount = "1,00") {
  await page
    .getByRole("navigation", { name: "Account navigation" })
    .getByRole("link", { name: "New transfer", exact: true })
    .click();
  const invoiceNumber = await page.locator(".invoice dd").nth(2).innerText();
  await page
    .getByLabel("Recipient name", { exact: true })
    .fill("North Studio sp. z o.o.");
  await page
    .getByLabel("Recipient account number", { exact: true })
    .fill(invoiceNumber);
  await page.getByLabel("Amount (PLN)", { exact: true }).fill(amount);
  await page
    .getByLabel("Transfer reference", { exact: true })
    .fill("Invoice FV/2026/104");
  await page.getByRole("button", { name: "Review transfer" }).click();
  await expect(
    page.getByRole("heading", { name: "Review transfer before confirming" }),
  ).toBeVisible();
}
async function approve(page: Page) {
  await page.getByLabel("Yes, this is my own decision").check();
  await page.getByLabel("I compared the recipient").check();
  await page.getByRole("button", { name: "Continue to confirmation" }).click();
  await page.getByLabel("Confirmation code", { exact: true }).fill("1234");
}

test("landing and public help work without the bank API; legacy study route has no code gate", async ({
  page,
}) => {
  const apiCalls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiCalls.push(request.url());
  });
  await page.route("**/api/**", (route) => route.abort());
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your finances." }),
  ).toBeVisible();
  await page.goto("/help");
  await expect(
    page.getByRole("heading", { name: "Help center" }),
  ).toBeVisible();
  expect(apiCalls).toEqual([]);
  await page.unroute("**/api/**");
  await page.goto("/study");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Login", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Participant code")).toHaveCount(0);
});

test("actual bank flow, reload preview, wrong OTP, once-only balance and history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await enter(page);
  const before = await (await page.request.get("/api/bank/account")).json();
  await prepare(page);
  const review = page.url();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Review transfer before confirming" }),
  ).toBeVisible();
  await approve(page);
  await page.getByLabel("Confirmation code", { exact: true }).fill("0000");
  await page.getByRole("button", { name: "Confirm PLN 1.00" }).click();
  await expect(page.getByRole("alert")).toContainText("The code is incorrect");
  await page.getByLabel("Confirmation code", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Confirm PLN 1.00" }).dblclick();
  await expect(
    page.getByRole("heading", { name: "Transfer completed" }),
  ).toBeVisible();
  await page.goto(review);
  await expect(
    page.getByRole("heading", { name: "Transfer completed" }),
  ).toBeVisible();
  const after = await (await page.request.get("/api/bank/account")).json();
  expect(after.balance_grosz).toBe(before.balance_grosz - 100);
  await page
    .getByRole("link", { name: "View history", exact: true })
    .click();
  await page.getByRole("searchbox").fill("nieistniejacy");
  await expect(
    page.getByRole("heading", { name: "No matching transactions" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByRole("searchbox")).toBeFocused();
  expect(errors).toEqual([]);
});

test("server hold cannot be undone by navigation; cancellation stays terminal", async ({
  page,
}) => {
  await enter(page);
  const before = await (await page.request.get("/api/bank/account")).json();
  await prepare(page);
  const review = page.url();
  await page.getByLabel("Someone is pressuring").check();
  await page.getByLabel("I compared the recipient").check();
  await page
    .getByRole("button", { name: "Hold transfer", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Transfer held" }),
  ).toBeVisible();
  await page.goto(review);
  await expect(
    page.getByRole("heading", { name: "Transfer held" }),
  ).toBeVisible();
  expect(
    (await (await page.request.get("/api/bank/account")).json()).balance_grosz,
  ).toBe(before.balance_grosz);
  await page.getByRole("link", { name: "Back to account", exact: true }).click();
  await prepare(page);
  const secondReview = page.url();
  await page
    .getByRole("button", { name: "Cancel transfer", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Transfer canceled" }),
  ).toBeVisible();
  await page.goto(secondReview);
  await expect(
    page.getByRole("heading", { name: "Transfer canceled" }),
  ).toBeVisible();
});

test("help preserves login and warning context; dirty draft offers a choice", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Login", { exact: true }).fill("anna.demo");
  await page.getByLabel("Password", { exact: true }).fill("bank24");
  await page
    .getByRole("link", { name: "I need help signing in" })
    .click();
  await page.getByRole("link", { name: "Back", exact: true }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("bank24");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Confirmation code", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Confirm sign-in" }).click();
  await prepare(page);
  await page.getByLabel("Yes, this is my own decision").check();
  await page.getByRole("link", { name: "Help", exact: true }).click();
  await page.getByRole("link", { name: "Back", exact: true }).click();
  await expect(page.getByLabel("Yes, this is my own decision")).toBeChecked();
  await page.getByRole("link", { name: "Account", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Account navigation" })
    .getByRole("link", { name: "New transfer", exact: true })
    .click();
  await page.getByLabel("Recipient name").fill("Draft");
  await page.getByRole("link", { name: "Account", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "What should happen to the draft?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Keep and leave" }).click();
  await page
    .getByRole("navigation", { name: "Account navigation" })
    .getByRole("link", { name: "New transfer", exact: true })
    .click();
  await expect(page.getByLabel("Recipient name")).toHaveValue("Draft");
});

test("lost submit response recovers the same completed operation", async ({
  page,
}) => {
  await enter(page);
  await prepare(page);
  await approve(page);
  await page.route("**/api/bank/transfers/*/submit", async (route) => {
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Confirm PLN 1.00" }).click();
  await expect(
    page.getByRole("heading", { name: "Transfer completed" }),
  ).toBeVisible();
  expect(page.url()).toContain("recover=1");
});

test("edited draft survives help; metadata contains no credentials; session loss clears access", async ({
  page,
  context,
}) => {
  const packets: unknown[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/telemetry/events"))
      packets.push(request.postDataJSON());
  });
  await enter(page, true);
  await prepare(page);
  await page.getByRole("link", { name: "Edit details", exact: true }).click();
  await page
    .getByLabel("Transfer reference", { exact: true })
    .fill("Edited draft");
  await page.getByRole("link", { name: "Help", exact: true }).click();
  await page.getByRole("link", { name: "Back", exact: true }).click();
  await expect(page.getByLabel("Transfer reference", { exact: true })).toHaveValue(
    "Edited draft",
  );
  await page.getByRole("button", { name: "Review transfer" }).click();
  expect(packets.length).toBeGreaterThan(0);
  expect(JSON.stringify(packets)).not.toContain("anna.demo");
  expect(JSON.stringify(packets)).not.toContain("bank24");
  expect(JSON.stringify(packets)).not.toContain("Edited draft");
  for (const packet of packets as { events: Record<string, unknown>[] }[])
    for (const event of packet.events) {
      expect(
        Object.keys(event).every((key) =>
          [
            "sequence",
            "time_ms",
            "type",
            "stage",
            "field",
            "length",
            "x",
            "y", "duration_ms", "width", "height", "delta_y", "env", "status", "keys", "features",
          ].includes(key),
        ),
      ).toBe(true);
    }
  await context.clearCookies();
  await page.goto("/app/history");
  await expect(
    page.getByRole("heading", { name: "Sign in to Bank24" }),
  ).toBeVisible();
  await expect(page.locator(".balance")).toHaveCount(0);
});

test("offline errors retain credentials; protected route does not expose account", async ({
  page,
  context,
}) => {
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Login", { exact: true }).fill("anna.demo");
  await page.getByLabel("Password", { exact: true }).fill("bank24");
  await context.setOffline(true);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("connect to the server");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("bank24");
  await context.setOffline(false);
});

test("responsive layout, keyboard and axe; fresh professional captures", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const directory = path.resolve("../.impeccable/review");
  fs.mkdirSync(directory, { recursive: true });
  await enter(page);
  const routes = [
    "/",
    "/app",
    "/app/history",
    "/app/transfers/new",
    "/help?return=%2Fapp",
  ];
  for (const route of routes) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    // 720 CSS pixels models a 1440 px desktop viewport at 200% browser zoom.
    for (const width of [320, 375, 720, 768, 900, 1024, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        route + " at " + width,
      ).toBe(true);
      if (route === "/app/transfers/new") {
        if (width >= 1024)
          await expect(page.locator(".camera-heading")).toBeVisible();
        else
          await expect(page.locator(".camera-body")).not.toHaveAttribute(
            "open",
          );
      }
    }
    for (const width of [375, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      const audit = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(
        audit.violations.map((item) => ({
          id: item.id,
          nodes: item.nodes.map((node) => node.target),
        })),
        route + " at " + width,
      ).toEqual([]);
    }
  }
  await page.goto("/app");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: path.join(directory, "react-dashboard-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 1000 });
  await page.screenshot({
    path: path.join(directory, "react-dashboard-mobile.png"),
    fullPage: true,
  });
  await page.goto("/app/transfers/new");
  await page.screenshot({
    path: path.join(directory, "react-transfer-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: path.join(directory, "react-transfer-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL("/");
  await page.screenshot({
    path: path.join(directory, "react-landing-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 1000 });
  await page.screenshot({
    path: path.join(directory, "react-landing-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("link", { name: /Sign in/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Sign in to Bank24", exact: true }),
  ).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  });
  await page.screenshot({
    path: path.join(directory, "react-login-desktop.png"),
    fullPage: true,
  });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.setViewportSize({ width: 375, height: 1000 });
  await page.screenshot({
    path: path.join(directory, "react-login-mobile.png"),
    fullPage: true,
  });
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(
    page.getByRole("link", { name: "Skip to content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  // Full flow screens, including long content and 200% reflow (720 CSS px).
  await page.getByLabel("Login", { exact: true }).fill("anna.demo");
  await page.getByLabel("Password", { exact: true }).fill("bank24");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  for (const width of [375, 768, 900, 1024, 1440, 1920, 720]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.getByLabel("Confirmation code", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Confirm sign-in" }).click();
  await prepare(page);
  await page.getByRole("link", { name: "Edit details", exact: true }).click();
  await page
    .getByLabel("Recipient name", { exact: true })
    .fill("Long recipient ".repeat(7).slice(0, 100));
  await page
    .getByLabel("Transfer reference", { exact: true })
    .fill("Long reference ".repeat(13).slice(0, 140));
  await page.getByRole("button", { name: "Review transfer" }).click();
  for (const stage of ["review", "confirm", "status"]) {
    for (const width of [375, 768, 900, 1024, 1440, 1920, 720]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        stage + " at " + width,
      ).toBe(true);
    }
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    if (stage === "review") {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.screenshot({
        path: path.join(directory, "react-review-desktop.png"),
        fullPage: true,
      });
      await page.setViewportSize({ width: 375, height: 1000 });
      await page.screenshot({
        path: path.join(directory, "react-review-mobile.png"),
        fullPage: true,
      });
      await page.getByLabel("Yes, this is my own decision").check();
      await page.getByLabel("I compared the recipient").check();
      await page
        .getByRole("button", { name: "Continue to confirmation" })
        .click();
    }
    if (stage === "confirm") {
      if (
        await page
          .getByRole("button", { name: "Request confirmation code", exact: true })
          .isVisible()
      )
        await page
          .getByRole("button", { name: "Request confirmation code", exact: true })
          .click();
      await page.getByLabel("Confirmation code", { exact: true }).fill("1234");
      await page.getByRole("button", { name: "Confirm PLN 1.00" }).click();
      await expect(
        page.getByRole("heading", { name: "Transfer completed" }),
      ).toBeVisible();
    }
  }
});

test.describe("camera transport and lifecycle", () => {
  test.use({
    permissions: ["camera"],
  });

  test("server-returned frames survive routes and logout releases tracks", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      const state = { calls: 0, tracks: [] as MediaStreamTrack[] };
      (window as unknown as { cameraTest: typeof state }).cameraTest = state;
      navigator.mediaDevices.getUserMedia = async () => {
        state.calls++;
        const canvas = document.createElement("canvas");
        canvas.width = 640;
        canvas.height = 480;
        const drawing = canvas.getContext("2d")!;
        const draw = () => {
          drawing.fillStyle = "#cbd5df";
          drawing.fillRect(0, 0, 640, 480);
          drawing.fillStyle = "#152b4b";
          drawing.fillRect(Date.now() % 400, 20, 30, 30);
        };
        draw();
        const timer = setInterval(draw, 66);
        const stream = canvas.captureStream(15);
        stream
          .getTracks()
          .forEach((track) =>
            track.addEventListener("ended", () => clearInterval(timer)),
          );
        state.tracks.push(...stream.getTracks());
        return stream;
      };
    });
    await enter(page);
    await page
      .getByRole("navigation", { name: "Account navigation" })
      .getByRole("link", { name: "New transfer", exact: true })
      .click();
    await expect(
      page.getByText("Analyzed preview from the server", { exact: true }),
    ).toBeVisible({ timeout: 30_000 });
    await page.setViewportSize({ width: 320, height: 850 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    for (const selector of [".icon-link", ".logout-button"]) {
      const box = await page.locator(selector).boundingBox();
      expect(box, selector).not.toBeNull();
      expect(box!.width, selector + " width").toBeGreaterThanOrEqual(44);
      expect(box!.height, selector + " height").toBeGreaterThanOrEqual(44);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(page.locator(".camera-preview img")).toBeVisible();
    await expect(page.locator(".camera-preview img")).toHaveAttribute(
      "src",
      /^data:image\/jpeg;base64,/,
    );
    await page.getByText("Session parameters", { exact: true }).click();
    await expect(page.locator(".metric-list").first()).toContainText(
      /Preview · no pulse estimation|Collecting samples/,
      { timeout: 30_000 },
    );
    await page.getByRole("navigation", { name: "Account navigation" }).getByRole("link", { name: "New transfer", exact: true }).click();
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { cameraTest: { calls: number } }).cameraTest
            .calls,
      ),
    ).toBe(1);
    await page.getByText("Measurement details", { exact: true }).click();
    await expect(page.getByText("640 × 480 px", { exact: true })).toBeVisible();
    await page
      .getByText("All landmark coordinates", { exact: true })
      .click();
    await expect(page.locator(".landmark-data pre")).toContainText("No landmarks in the current measurement.");
    await page.getByRole("link", { name: "Help", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Turn off camera", exact: true }),
    ).toBeVisible();
    const permissionsUpdated = page.waitForResponse((response) =>
      response.url().endsWith("/api/session/permissions"),
    );
    await page
      .getByRole("button", { name: "Turn off camera", exact: true })
      .click();
    await permissionsUpdated;
    await expect(
      page.getByRole("button", { name: "Turn off camera", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("link", { name: "Back", exact: true }).click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Your finances." }),
    ).toBeVisible();
    expect(
      await page.evaluate(() =>
        (
          window as unknown as { cameraTest: { tracks: MediaStreamTrack[] } }
        ).cameraTest.tracks.every((track) => track.readyState === "ended"),
      ),
    ).toBe(true);
  });

  test("cancelled delayed permission stops the late stream without creating a session", async ({
    page,
  }) => {
    let sessions = 0;
    page.on("request", (request) => {
      if (request.url().endsWith("/api/frames/sessions")) sessions++;
    });
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 640;
        canvas.height = 480;
        canvas.getContext("2d")!.fillRect(0, 0, 640, 480);
        const stream = canvas.captureStream(15);
        (window as unknown as { lateTracks: MediaStreamTrack[] }).lateTracks =
          stream.getTracks();
        await new Promise((resolve) => setTimeout(resolve, 700));
        return stream;
      };
    });
    await enter(page);
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (
              window as unknown as { lateTracks?: MediaStreamTrack[] }
            ).lateTracks?.every((track) => track.readyState === "ended") ||
            false,
        ),
      )
      .toBe(true);
    expect(sessions).toBe(0);
  });
});

test("camera profile explains activation, shows live scores and reports unavailable analysis", async ({ page }) => {
  let needsSignIn = true;
  let modelUnavailable = false;
  await page.route("**/api/bank/camera-profile", (route) => route.fulfill({ json: {
    status: "ready", samples: 3, pending: 0, required: 3, version: 1,
    updated_at: Date.now() / 1000, recorded_this_session: needsSignIn,
    activates_next_sign_in: needsSignIn, model_available: true, started_at: null,
    approval_available: false, can_enroll: false,
  } }));
  await page.route("**/api/bank/risk-check", (route) => route.fulfill({ json: {
    status: modelUnavailable ? "insufficient_data" : "ok", limit: null,
    account_takeover_risk: modelUnavailable ? null : 37,
    reason: modelUnavailable ? "The fusion checkpoint is only a Git LFS pointer." : null,
    retry_after: null,
  } }));
  // Keep this presentation test independent of the worker and its session capacity.
  await page.route("**/api/frames/sessions**", (route) => route.fulfill({ json:
    route.request().url().endsWith("/frame")
      ? { measurement: { timestamp: Date.now() / 1000, status: "preview", heart_rate_bpm: null }, image: "" }
      : { session_id: "profile-display-test", ok: true },
  }));
  await enter(page);
  await expect(page.getByText(/Your samples are saved. Sign out and sign in again/)).toBeVisible();
  await expect(page.getByText(/Experimental owner profile mismatch:/)).toHaveCount(0);

  needsSignIn = false;
  await page.reload();
  await expect(page.getByText(/Experimental owner profile mismatch: 37\/100/)).toBeVisible({ timeout: 15_000 });
  modelUnavailable = true;
  await expect(page.getByText(/Camera score unavailable. The fusion checkpoint is only a Git LFS pointer/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Experimental owner profile mismatch:/)).toHaveCount(0);
});


test("consented browser measurements include real keyboard windows and connection timings", async ({ page }) => {
  const events: Record<string, unknown>[] = [];
  const failures: number[] = [];
  page.on("request", request => {
    if (request.url().endsWith("/api/telemetry/events")) events.push(...request.postDataJSON().events);
  });
  page.on("response", response => {
    if (response.url().endsWith("/api/telemetry/events") && !response.ok()) failures.push(response.status());
  });
  await enter(page, true);
  await page.getByRole("navigation", { name: "Account navigation" }).getByRole("link", { name: "New transfer", exact: true }).click();
  const keyboardAccepted = page.waitForResponse(response => response.url().endsWith("/api/telemetry/events") &&
    response.request().postDataJSON().events.some((event: { type: string }) => event.type === "keyboard_window"));
  await page.getByLabel("Recipient name", { exact: true }).pressSequentially("abcdefghijklmnopqrst", { delay: 30 });
  for (let i = 0; i < 10; i++) await page.mouse.move(100 + i * 20, 200 + i * 5);
  await expect.poll(() => events.some(event => event.type === "keyboard_window")).toBe(true);
  await expect.poll(() => events.some(event => event.type === "ping")).toBe(true);
  expect(events.some(event => event.type === "environment")).toBe(true);
  expect(events.some(event => event.type === "server_request")).toBe(true);
  expect(events.some(event => event.type === "pointer")).toBe(true);
  expect(events.filter(event => event.type === "keyboard_window").every(event => event.field !== "password")).toBe(true);
  expect((await keyboardAccepted).status()).toBe(200);
  expect(failures).toEqual([]);
});
