const { chromium } = require('C:/Users/micha/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = __dirname;
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const page = await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.goto('http://localhost:5174');
    await page.evaluate(()=>document.fonts.ready);
    assert.equal(await page.locator('#camera-parameters').evaluate(e=>e.open),false);
    await page.locator('#login').fill('wrong');await page.locator('#password').fill('wrong');
    await page.getByRole('button',{name:'Zaloguj się',exact:true}).click();
    assert(await page.locator('#form-error').isVisible());
    await page.locator('#login').fill('anna.demo');await page.locator('#password').fill('bank24');
    await page.getByRole('button',{name:'Pokaż hasło'}).click();
    assert.equal(await page.locator('#password').getAttribute('type'),'text');
    await page.getByRole('button',{name:'Ukryj hasło'}).click();await page.locator('#remember').check();
    await page.getByRole('button',{name:'Zaloguj się',exact:true}).click();await page.waitForURL('**/#sms');
    await page.locator('#sms-code').fill('1111');await page.getByRole('button',{name:'Potwierdź i przejdź do konta'}).click();assert(await page.locator('#form-error').isVisible());
    await page.locator('#sms-code').fill('1234');await page.getByRole('button',{name:'Potwierdź i przejdź do konta'}).click();await page.waitForURL('**/#dashboard');
    await page.getByRole('button',{name:'Nowy przelew'}).click();await page.waitForURL('**/#transfer');
    assert.equal(await page.locator('#beneficiary').inputValue(),'');
    await page.locator('#beneficiary').fill('Pracownia Forma');await page.locator('#account').fill('123');await page.locator('#amount').fill('1250,00');await page.locator('#title').fill('Faktura FV/10/2026');
    await page.getByRole('button',{name:'Sprawdź przelew'}).click();assert((await page.locator('#form-error').textContent()).includes('26 cyfr'));
    await page.locator('#account').fill('12 3456 7890 1234 5678 9012 3456');await page.getByRole('button',{name:'Sprawdź przelew'}).click();await page.waitForURL('**/#review');
    await page.getByRole('button',{name:'Przejdź do potwierdzenia'}).click();await page.waitForURL('**/#warning');
    await page.getByRole('button',{name:'Tak, ktoś mnie instruuje'}).click();assert(await page.locator('#safety-response').isVisible());
    await page.getByRole('button',{name:'Anuluj przelew'}).click();await page.waitForURL('**/#result');assert((await page.locator('h1').textContent()).includes('anulowany'));
    await page.getByRole('button',{name:'Ostrzeżenie',exact:true}).click();await page.waitForURL('**/#warning');await page.getByRole('button',{name:'Nie, robię to samodzielnie'}).click();await page.getByRole('button',{name:'Zakończ podgląd'}).click();await page.waitForURL('**/#result');
    await page.getByRole('button',{name:'Włącz kamerę'}).click();await page.getByRole('button',{name:'Uruchom podgląd'}).click();assert(await page.locator('#camera-error').isVisible());
    await page.locator('#camera-agreement').check();await page.getByRole('button',{name:'Uruchom podgląd'}).click();await page.waitForFunction(()=>document.querySelector('#local-video').srcObject?.active);
    await page.getByRole('button',{name:'Przelew',exact:true}).click();await page.waitForURL('**/#transfer');assert(await page.locator('#local-video').isVisible());
    await page.getByRole('button',{name:'Wyloguj',exact:true}).click();await page.waitForURL('**/#login');assert.equal(await page.locator('#local-video').evaluate(e=>e.srcObject),null);
    assert.equal(await page.locator('#remember').isChecked(),false);
    for(const route of ['dashboard','transfer','warning']){
      await page.goto(`http://localhost:5174/#${route}`);
      const heading=await page.locator('h1').textContent();
      await page.locator('.skip-link').focus();await page.keyboard.press('Enter');
      assert.equal(new URL(page.url()).hash,`#${route}`);
      assert.equal(await page.locator('h1').textContent(),heading);
      assert.equal(await page.evaluate(()=>document.activeElement.id),'screen');
    }
    const overflow=[];
    for(const width of [375,768,1024,1440]){
      await page.setViewportSize({width,height:1000});
      for(const route of ['login','sms','dashboard','transfer','warning']){
        await page.goto(`http://localhost:5174/#${route}`);await page.evaluate(()=>document.fonts.ready);
        const dimensions=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));
        if(dimensions.scroll>dimensions.client+1)overflow.push({width,route,...dimensions});
      }
    }
    assert.deepEqual(overflow,[],'No horizontal overflow');
    const screenshots=[];
    for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}]){
      await page.setViewportSize(viewport);
      for(const route of ['login','sms','dashboard','transfer','warning']){
        await page.goto(`http://localhost:5174/#${route}`);await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(output,`${viewport.name}-${route}.png`),fullPage:true});screenshots.push(`${viewport.name}-${route}.png`);
      }
    }
    await page.setViewportSize({width:1440,height:1000});await page.goto('http://localhost:5174/#login');await page.locator('#camera-parameters > summary').click();await page.screenshot({path:path.join(output,'desktop-parameters.png'),fullPage:true});
    assert.deepEqual(errors,[],'No browser runtime errors');
    const report={passed:true,checks:['Login validation and password toggle','SMS validation','Manual transfer and account validation','Review and warning','Both warning answers','Camera consent and local preview with simulated camera','Camera persists across routes and stops at logout','Parameters initially collapsed','Keyboard skip link preserves dashboard/transfer/warning and focuses content','No overflow at 375/768/1024/1440 on five screens','No browser runtime errors'],screenshots};
    fs.writeFileSync(path.join(output,'smoke-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  } catch(error){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
