const { chromium } = require('playwright');

(async () => {
    try {
        console.log('Launching browser...');
        const browser = await chromium.launch({ headless: true });
        console.log('Creating page...');
        const page = await browser.newPage();
        console.log('Navigating...');
        await page.goto('http://localhost:5173');
        console.log('Page title:', await page.title());
        await browser.close();
        console.log('Success!');
    } catch (error) {
        console.error('Test failed:', error);
    }
})();
