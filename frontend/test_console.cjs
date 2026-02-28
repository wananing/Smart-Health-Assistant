const { chromium } = require('playwright');

(async () => {
    try {
        const browser = await chromium.launch({ headless: true });
        const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
        const page = await context.newPage();

        page.on('console', msg => console.log('PAGE LOG:', msg.text()));
        page.on('pageerror', err => console.log('PAGE ERROR:', err));
        page.on('requestfailed', req => console.log('REQ FAILED:', req.url(), req.failure().errorText));

        await page.goto('http://localhost:5173');
        await page.waitForLoadState('networkidle');

        console.log('Page title:', await page.title());
        const bodyContent = await page.evaluate(() => document.body.innerHTML);
        console.log('Body length:', bodyContent.length);

        await browser.close();
    } catch (err) {
        console.error(err);
    }
})();
