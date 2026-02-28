/**
 * Full console/error capture test on port 5174
 */
const { chromium } = require('playwright');

(async () => {
    try {
        const browser = await chromium.launch({ headless: true });
        const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
        const page = await context.newPage();

        const consoleMessages = [];
        const pageErrors = [];
        page.on('console', msg => {
            if (msg.type() === 'error') consoleMessages.push(`[ERROR] ${msg.text()}`);
        });
        page.on('pageerror', err => pageErrors.push(`[PAGE ERROR] ${err.message}`));

        await page.goto('http://localhost:5174', { timeout: 10000 });
        await page.waitForLoadState('networkidle', { timeout: 10000 });

        const bodyHTML = await page.evaluate(() => document.body.innerHTML);
        const title = await page.title();
        console.log('Title:', title);
        console.log('Body length:', bodyHTML.length);
        console.log('Body snippet:', bodyHTML.substring(0, 600));

        if (consoleMessages.length) {
            console.log('\n--- Console Errors ---');
            consoleMessages.forEach(m => console.log(m));
        }
        if (pageErrors.length) {
            console.log('\n--- Page Errors (uncaught) ---');
            pageErrors.forEach(e => console.log(e));
        }

        await page.screenshot({ path: '/tmp/debug_blank.png', fullPage: true });
        console.log('\nScreenshot: /tmp/debug_blank.png');

        await browser.close();
    } catch (err) {
        console.error('Crash:', err.message);
    }
})();
