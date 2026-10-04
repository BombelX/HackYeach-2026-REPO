import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";

async function enter(page: Page, telemetry = false) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Twoje finanse." }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: /Zaloguj się/ })
    .first()
    .click();
  if (telemetry) await page.getByLabel(/Pomóż ulepszać demonstrację/).check();
  await page.getByLabel("Login", { exact: true }).fill("anna.demo");
  await page.getByLabel("Hasło", { exact: true }).fill("bank24");
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();
  await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Potwierdź logowanie" }).click();
  await expect(
    page.getByRole("heading", { name: "Dzień dobry" }),
  ).toBeVisible();
}
async function prepare(page: Page, amount = "1,00") {
  await page
    .getByRole("navigation", { name: "Nawigacja konta" })
    .getByRole("link", { name: "Nowy przelew", exact: true })
    .click();
  const invoiceNumber = await page.locator(".invoice dd").nth(2).innerText();
  await page
    .getByLabel("Nazwa odbiorcy", { exact: true })
    .fill("North Studio sp. z o.o.");
  await page
    .getByLabel("Numer rachunku odbiorcy", { exact: true })
    .fill(invoiceNumber);
  await page.getByLabel("Kwota (PLN)", { exact: true }).fill(amount);
  await page
    .getByLabel("Tytuł przelewu", { exact: true })
    .fill("Faktura FV/2026/104");
  await page.getByRole("button", { name: "Sprawdź przelew" }).click();
  await expect(
    page.getByRole("heading", { name: "Sprawdź przelew przed potwierdzeniem" }),
  ).toBeVisible();
}
async function approve(page: Page) {
  await page.getByLabel("Tak, podejmuję decyzję samodzielnie").check();
  await page.getByLabel("Porównałem odbiorcę").check();
  await page.getByRole("button", { name: "Przejdź do potwierdzenia" }).click();
  await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("1234");
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
    page.getByRole("heading", { name: "Twoje finanse." }),
  ).toBeVisible();
  await page.goto("/help");
  await expect(
    page.getByRole("heading", { name: "Centrum pomocy" }),
  ).toBeVisible();
  expect(apiCalls).toEqual([]);
  await page.unroute("**/api/**");
  await page.goto("/study");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Login", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Kod uczestnika")).toHaveCount(0);
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
    page.getByRole("heading", { name: "Sprawdź przelew przed potwierdzeniem" }),
  ).toBeVisible();
  await approve(page);
  await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("0000");
  await page.getByRole("button", { name: "Potwierdź 1,00 zł" }).click();
  await expect(page.getByRole("alert")).toContainText("Kod jest niepoprawny");
  await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Potwierdź 1,00 zł" }).dblclick();
  await expect(
    page.getByRole("heading", { name: "Przelew zrealizowany" }),
  ).toBeVisible();
  await page.goto(review);
  await expect(
    page.getByRole("heading", { name: "Przelew zrealizowany" }),
  ).toBeVisible();
  const after = await (await page.request.get("/api/bank/account")).json();
  expect(after.balance_grosz).toBe(before.balance_grosz - 100);
  await page
    .getByRole("link", { name: "Zobacz historię", exact: true })
    .click();
  await page.getByRole("searchbox").fill("nieistniejacy");
  await expect(
    page.getByRole("heading", { name: "Nie znaleziono operacji" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Wyczyść filtry" }).click();
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
  await page.getByLabel("Ktoś wywiera").check();
  await page.getByLabel("Porównałem odbiorcę").check();
  await page
    .getByRole("button", { name: "Wstrzymaj przelew", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Przelew wstrzymany" }),
  ).toBeVisible();
  await page.goto(review);
  await expect(
    page.getByRole("heading", { name: "Przelew wstrzymany" }),
  ).toBeVisible();
  expect(
    (await (await page.request.get("/api/bank/account")).json()).balance_grosz,
  ).toBe(before.balance_grosz);
  await page.getByRole("link", { name: "Wróć do konta", exact: true }).click();
  await prepare(page);
  const secondReview = page.url();
  await page
    .getByRole("button", { name: "Anuluj przelew", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Przelew anulowany" }),
  ).toBeVisible();
  await page.goto(secondReview);
  await expect(
    page.getByRole("heading", { name: "Przelew anulowany" }),
  ).toBeVisible();
});

test("help preserves login and warning context; dirty draft offers a choice", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Login", { exact: true }).fill("anna.demo");
  await page.getByLabel("Hasło", { exact: true }).fill("bank24");
  await page
    .getByRole("link", { name: "Potrzebuję pomocy z logowaniem" })
    .click();
  await page.getByRole("link", { name: "Wróć", exact: true }).click();
  await expect(page.getByLabel("Hasło", { exact: true })).toHaveValue("bank24");
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();
  await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Potwierdź logowanie" }).click();
  await prepare(page);
  await page.getByLabel("Tak, podejmuję").check();
  await page.getByRole("link", { name: "Pomoc", exact: true }).click();
  await page.getByRole("link", { name: "Wróć", exact: true }).click();
  await expect(page.getByLabel("Tak, podejmuję")).toBeChecked();
  await page.getByRole("link", { name: "Konto", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Nawigacja konta" })
    .getByRole("link", { name: "Nowy przelew", exact: true })
    .click();
  await page.getByLabel("Nazwa odbiorcy").fill("Szkic");
  await page.getByRole("link", { name: "Konto", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Co zrobić ze szkicem?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Zachowaj i wyjdź" }).click();
  await page
    .getByRole("navigation", { name: "Nawigacja konta" })
    .getByRole("link", { name: "Nowy przelew", exact: true })
    .click();
  await expect(page.getByLabel("Nazwa odbiorcy")).toHaveValue("Szkic");
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
  await page.getByRole("button", { name: "Potwierdź 1,00 zł" }).click();
  await expect(
    page.getByRole("heading", { name: "Przelew zrealizowany" }),
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
  await page.getByRole("link", { name: "Edytuj dane", exact: true }).click();
  await page
    .getByLabel("Tytuł przelewu", { exact: true })
    .fill("Zmieniony szkic");
  await page.getByRole("link", { name: "Pomoc", exact: true }).click();
  await page.getByRole("link", { name: "Wróć", exact: true }).click();
  await expect(page.getByLabel("Tytuł przelewu", { exact: true })).toHaveValue(
    "Zmieniony szkic",
  );
  await page.getByRole("button", { name: "Sprawdź przelew" }).click();
  expect(packets.length).toBeGreaterThan(0);
  expect(JSON.stringify(packets)).not.toContain("anna.demo");
  expect(JSON.stringify(packets)).not.toContain("bank24");
  expect(JSON.stringify(packets)).not.toContain("Zmieniony szkic");
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
            "y",
          ].includes(key),
        ),
      ).toBe(true);
    }
  await context.clearCookies();
  await page.goto("/app/history");
  await expect(
    page.getByRole("heading", { name: "Zaloguj się do Bank24" }),
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
  await page.getByLabel("Hasło", { exact: true }).fill("bank24");
  await context.setOffline(true);
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("połączyć z serwerem");
  await expect(page.getByLabel("Hasło", { exact: true })).toHaveValue("bank24");
  await context.setOffline(false);
});

test("responsive layout, keyboard and axe; fresh professional captures", async ({
  page,
}) => {
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
  await page.getByRole("button", { name: "Wyloguj", exact: true }).click();
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
    .getByRole("link", { name: /Zaloguj się/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Zaloguj się do Bank24", exact: true }),
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
    page.getByRole("link", { name: "Przejdź do treści" }),
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
  await page.getByLabel("Hasło", { exact: true }).fill("bank24");
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click();
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
  await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("1234");
  await page.getByRole("button", { name: "Potwierdź logowanie" }).click();
  await prepare(page);
  await page.getByRole("link", { name: "Edytuj dane", exact: true }).click();
  await page
    .getByLabel("Nazwa odbiorcy", { exact: true })
    .fill("Długi odbiorca ".repeat(7).slice(0, 100));
  await page
    .getByLabel("Tytuł przelewu", { exact: true })
    .fill("Długi tytuł ".repeat(13).slice(0, 140));
  await page.getByRole("button", { name: "Sprawdź przelew" }).click();
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
      await page.getByLabel("Tak, podejmuję").check();
      await page.getByLabel("Porównałem odbiorcę").check();
      await page
        .getByRole("button", { name: "Przejdź do potwierdzenia" })
        .click();
    }
    if (stage === "confirm") {
      if (
        await page
          .getByRole("button", { name: "Zamów kod potwierdzenia", exact: true })
          .isVisible()
      )
        await page
          .getByRole("button", { name: "Zamów kod potwierdzenia", exact: true })
          .click();
      await page.getByLabel("Kod potwierdzenia", { exact: true }).fill("1234");
      await page.getByRole("button", { name: "Potwierdź 1,00 zł" }).click();
      await expect(
        page.getByRole("heading", { name: "Przelew zrealizowany" }),
      ).toBeVisible();
    }
  }
});

test.describe("camera transport and lifecycle", () => {
  test.use({
    permissions: ["camera"],
  });

  test("one real WebRTC session survives routes; stale values are hidden; logout releases tracks", async ({
    page,
  }) => {
    await enter(page);
    await page
      .getByRole("navigation", { name: "Nawigacja konta" })
      .getByRole("link", { name: "Nowy przelew", exact: true })
      .click();
    await page.evaluate(() => {
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
    await page
      .getByRole("button", { name: "Włącz kamerę", exact: true })
      .click();
    await page.getByLabel("Zgadzam się na transmisję").check();
    await page
      .getByRole("button", { name: "Uruchom kamerę", exact: true })
      .click();
    await expect(
      page.getByText("Analizowany podgląd z serwera", { exact: true }),
    ).toBeVisible({ timeout: 30_000 });
    await page.setViewportSize({ width: 320, height: 850 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    for (const selector of [".icon-link", ".logout-button", ".camera-stop"]) {
      const box = await page.locator(selector).boundingBox();
      expect(box, selector).not.toBeNull();
      expect(box!.width, selector + " width").toBeGreaterThanOrEqual(44);
      expect(box!.height, selector + " height").toBeGreaterThanOrEqual(44);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect
      .poll(() =>
        page.evaluate(() => document.querySelector("video")!.readyState),
      )
      .toBeGreaterThan(1);
    await page.getByText("Parametry sesji", { exact: true }).click();
    await expect(page.locator(".metric-list").first()).toContainText(
      /Podgląd · analiza wyłączona|Zbieranie próbek/,
      { timeout: 30_000 },
    );
    await page.getByRole("link", { name: "Nowy przelew", exact: true }).click();
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { cameraTest: { calls: number } }).cameraTest
            .calls,
      ),
    ).toBe(1);
    await page.route("**/api/sessions/*/output", (route) =>
      route.fulfill({
        json: {
          session_id: "camera-123",
          timestamp: Date.now() / 1000,
          status: "measuring",
          heart_rate_bpm: 72.4,
          heart_rate_stale: false,
          heart_rate_updated_at: Date.now() / 1000,
          face_detected: true,
          sampling_fps: 30,
          window_seconds: 10,
          landmarks: {
            pose: [{ index: 0, x: 0.5, y: 0.2, z: 0 }],
            face: [
              { index: 0, x: 0.4, y: 0.3, z: 0 },
              { index: 1, x: 0.6, y: 0.3, z: 0 },
            ],
          },
          landmarks_timestamp_ms: 123_456,
          frame_width: 640,
          frame_height: 480,
          error: null,
        },
      }),
    );
    await expect(page.locator(".metric-list").first()).toContainText("72 BPM");
    await expect(page.locator(".metric-list").first()).toContainText("1");
    await expect(page.locator(".metric-list").first()).toContainText("2");
    await page.getByText("Szczegóły pomiaru", { exact: true }).click();
    await expect(page.getByText("640 × 480 px", { exact: true })).toBeVisible();
    await page
      .getByText("Wszystkie współrzędne landmarków", { exact: true })
      .click();
    await expect(page.locator(".landmark-data pre")).toContainText('"pose"');
    await page.unroute("**/api/sessions/*/output");
    await page.route("**/api/sessions/*/output", (route) =>
      route.fulfill({
        json: {
          session_id: "camera-123",
          timestamp: Date.now() / 1000 - 10,
          status: "measuring",
          heart_rate_bpm: 99,
          heart_rate_stale: false,
          heart_rate_updated_at: Date.now() / 1000 - 10,
          face_detected: true,
          sampling_fps: 30,
          window_seconds: 10,
          landmarks: { pose: [], face: [] },
          landmarks_timestamp_ms: 123_456,
          frame_width: 640,
          frame_height: 480,
          error: null,
        },
      }),
    );
    await expect(
      page.getByText("Pomiar nieaktualny. Czekamy na nowe dane."),
    ).toBeVisible();
    await expect(page.locator(".metric-list").first()).not.toContainText("99");
    await page.getByRole("link", { name: "Pomoc", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Wyłącz kamerę", exact: true }),
    ).toBeVisible();
    const permissionsUpdated = page.waitForResponse((response) =>
      response.url().endsWith("/api/session/permissions"),
    );
    await page
      .getByRole("button", { name: "Wyłącz kamerę", exact: true })
      .click();
    await permissionsUpdated;
    await expect(
      page.getByRole("button", { name: "Wyłącz kamerę", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("link", { name: "Wróć", exact: true }).click();
    await page.getByRole("button", { name: "Wyloguj", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Twoje finanse." }),
    ).toBeVisible();
    expect(
      await page.evaluate(() =>
        (
          window as unknown as { cameraTest: { tracks: MediaStreamTrack[] } }
        ).cameraTest.tracks.every((track) => track.readyState === "ended"),
      ),
    ).toBe(true);
  });

  test("cancelled delayed permission stops the late stream without sending an offer", async ({
    page,
  }) => {
    await enter(page);
    await page
      .getByRole("navigation", { name: "Nawigacja konta" })
      .getByRole("link", { name: "Nowy przelew", exact: true })
      .click();
    let offers = 0;
    page.on("request", (request) => {
      if (request.url().endsWith("/api/webrtc/offer")) offers++;
    });
    await page.evaluate(() => {
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
    await page
      .getByRole("button", { name: "Włącz kamerę", exact: true })
      .click();
    await page.getByLabel("Zgadzam się na transmisję").check();
    await page
      .getByRole("button", { name: "Uruchom kamerę", exact: true })
      .click();
    await page
      .locator(".camera-actions")
      .getByRole("button", { name: "Wyłącz kamerę", exact: true })
      .click();
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
    expect(offers).toBe(0);
  });
});
