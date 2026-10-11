import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;
const output = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
try {
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    async function capture(name) {
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: path.join(output, `${name}-${viewport.width}.png`), fullPage: true });
      const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      const layout = await page.evaluate(() => ({
        viewportWidth: innerWidth,
        pageWidth: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
        headings: [...document.querySelectorAll('h1')].map(el => ({ text: el.textContent, tabindex: el.getAttribute('tabindex') })),
        main: (() => { const r = document.querySelector('main').getBoundingClientRect(); return { x: r.x, width: r.width, y: r.y }; })(),
        smallTargets: [...document.querySelectorAll('button,a,input,summary')].filter(el => {
          const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && (r.height < 44 || r.width < 44);
        }).map(el => ({ text: el.textContent?.trim().slice(0,70), tag: el.tagName, width: Math.round(el.getBoundingClientRect().width), height: Math.round(el.getBoundingClientRect().height) })),
        cameraVisible: !!document.querySelector('.camera-slot') && !document.querySelector('.camera-slot').hidden,
      }));
      const entry = { name, viewport: viewport.width, url: page.url(), layout, violations: accessibility.violations.map(v => ({ id: v.id, impact: v.impact, description: v.description, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })), errors: [...errors] };
      results.push(entry);
      console.log(JSON.stringify({ name, viewport: viewport.width, overflow: layout.pageWidth > viewport.width, violations: entry.violations.map(v => v.id), mainWidth: layout.main.width }));
    }
    await page.goto('http://localhost:5181/study');
    await page.getByLabel('Participant code').waitFor();
    await capture('study');
    await page.getByLabel('Participant code').fill('DEMO-24');
    await page.getByRole('button', { name: 'Start', exact: true }).click();
    await page.getByLabel('Rozumiem zasady').waitFor();
    await capture('consent');
    await page.getByLabel('Rozumiem zasady').check();
    await page.getByRole('button', { name: 'Go to sign in' }).click();
    await page.getByLabel('Login', { exact: true }).waitFor();
    await capture('login');
    await page.getByLabel('Login', { exact: true }).fill('anna.demo');
    await page.getByLabel('Password', { exact: true }).fill('bank24');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByLabel('Confirmation code', { exact: true }).waitFor();
    await capture('login-otp');
    await page.getByLabel('Confirmation code', { exact: true }).fill('1234');
    await page.getByRole('button', { name: 'Confirm sign-in' }).click();
    await page.waitForURL('**/app');
    await page.getByText('Available funds', { exact: true }).waitFor();
    await capture('dashboard');
    const account = await (await page.request.get('http://localhost:5181/api/bank/account')).json();
    await page.goto('http://localhost:5181/app/history');
    await page.getByRole('searchbox').waitFor();
    await capture('history');
    const filters = await page.locator('.history-filters').evaluate(el => [...el.children].map(child => ({ tag: child.tagName, text: child.textContent, role: child.getAttribute('role'), tabIndex: child.tabIndex })));
    results.push({ name: 'history-filter-semantics', viewport: viewport.width, filters });
    await page.goto('http://localhost:5181/app/transfers/new');
    await page.getByLabel('Recipient name', { exact: true }).waitFor();
    await capture('transfer');
    await page.getByLabel('Recipient name', { exact: true }).fill(account.invoice.recipient);
    await page.getByLabel('Recipient account number', { exact: true }).fill(account.invoice.number);
    await page.getByLabel('Transfer reference', { exact: true }).fill(account.invoice.title);
    await page.getByLabel('Amount (PLN)', { exact: true }).fill('1,00');
    await page.getByRole('button', { name: 'Review transfer' }).click();
    await page.getByRole('heading', { name: 'Security verification' }).waitFor();
    await capture('review');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByLabel('Yes, this is my own decision').waitFor();
    await capture('intervention');
    await page.getByLabel('Yes, this is my own decision').check();
    await page.getByLabel('I compared the recipient').check();
    await page.getByRole('button', { name: 'Continue to confirmation' }).click();
    await page.getByRole('button', { name: 'Request confirmation code', exact: true }).waitFor();
    await capture('confirm');
    await page.getByRole('button', { name: 'Request confirmation code', exact: true }).click();
    await page.getByLabel('Confirmation code', { exact: true }).fill('1234');
    await page.getByRole('button', { name: 'Confirm PLN 1.00', exact: true }).click();
    await page.getByRole('heading', { name: 'Transfer completed' }).waitFor();
    await capture('result');
    await page.goto('http://localhost:5181/help?return=%2Fapp');
    await page.getByRole('heading', { name: 'Help center' }).waitFor();
    await capture('help');
    await context.close();
  }
} finally {
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(results, null, 2));
  await browser.close();
}
