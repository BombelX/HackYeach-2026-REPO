import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const output = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch({ channel: 'chrome' });
const results = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto('http://localhost:5181/study');
  await page.getByLabel('Kod uczestnika').fill('DEMO-24');
  await page.getByRole('button', { name: 'Rozpocznij', exact: true }).click();
  await page.getByLabel('Rozumiem zasady').check();
  await page.getByRole('button', { name: 'Przejdź do logowania' }).click();
  await page.getByLabel('Login', { exact: true }).fill('anna.demo');
  await page.getByLabel('Hasło', { exact: true }).fill('bank24');
  await page.getByRole('button', { name: 'Zaloguj się', exact: true }).click();
  await page.getByLabel('Kod potwierdzenia', { exact: true }).fill('1234');
  await page.getByRole('button', { name: 'Potwierdź logowanie' }).click();
  await page.waitForURL('**/app');
  results.push({ name: 'dashboard-focus', active: await page.evaluate(() => ({ tag: document.activeElement.tagName, text: document.activeElement.textContent?.slice(0,100) })) });
  for (const width of [390, 768, 1024]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of ['/app', '/app/transfers/new']) {
      await page.goto('http://localhost:5181' + route);
      await page.locator(route === '/app' ? '.balance' : '#recipient').waitFor();
      const metrics = await page.evaluate(() => ({
        mainWidth: document.querySelector('main').getBoundingClientRect().width,
        grid: getComputedStyle(document.querySelector('.layout')).gridTemplateColumns,
        clipped: [...document.querySelectorAll('.account-overview,.month-summary,.ledger li,.transfer-form,.invoice')].map(el => ({ selector: el.className, right: Math.round(el.getBoundingClientRect().right), shellRight: Math.round(document.querySelector('.app-shell').getBoundingClientRect().right) })).filter(item => item.right > item.shellRight),
      }));
      results.push({ route, width, ...metrics });
      console.log(JSON.stringify(results.at(-1)));
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('http://localhost:5181/app');
  await page.locator('.notification-dot').click();
  await page.waitForURL('**/study');
  results.push({ name: 'bell-click', result: 'logs-out', url: page.url() });
} finally {
  await fs.writeFile(path.join(output, 'layout-evidence.json'), JSON.stringify(results, null, 2));
  await browser.close();
}
