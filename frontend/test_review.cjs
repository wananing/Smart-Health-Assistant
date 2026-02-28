const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SCREENSHOTS_DIR = path.join(__dirname, 'review_screenshots');
if (!fs.existsSync(SCREENSHOTS_DIR)) {
    fs.mkdirSync(SCREENSHOTS_DIR);
}

const errors = [];
function check(condition, msg) {
    if (condition) {
        console.log(`  ✅ ${msg}`);
    } else {
        console.error(`  ❌ ${msg}`);
        errors.push(msg);
    }
}

async function review(page, step) {
    const p = path.join(SCREENSHOTS_DIR, `${step}.png`);
    await page.screenshot({ path: p, fullPage: false });
    console.log(`[SCREENSHOT] ${step} -> ${p}`);
}

(async () => {
    try {
        const browser = await chromium.launch({ headless: true });
        // Use an iPhone-like viewport for the mobile app
        const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
        const page = await context.newPage();

        console.log('Navigating to app...');
        await page.goto('http://localhost:5174');
        await page.waitForLoadState('networkidle');

        await review(page, '01_home_screen');
        console.log('\n=== Module 01: Home Screen ===');
        check(await page.locator('text=大健康 AI 助手在线中').isVisible(), "AI assistant badge visible");
        check(await page.locator('text=长辈模式').isVisible(), "Elder mode toggle visible");
        check(await page.locator('text=8,542').isVisible(), "Step count on health card visible");

        console.log('\n=== InputBar & SuggestionScroller ===');
        const inputEl = page.locator('input[type=text]').first();
        check(await inputEl.isVisible(), "Input bar visible");
        await inputEl.fill("我失眠了");
        await page.keyboard.press('Enter');
        await page.waitForTimeout(200);
        check(await page.locator('text=我失眠了').isVisible(), "User message appears in chat");
        await page.waitForTimeout(900); // wait for AI simulated responses
        await review(page, '02_chat_after_send');

        console.log('\n=== Module 02: AI Clinic Screen ===');
        await page.locator('footer span:has-text("AI诊室")').first().click();
        await page.waitForTimeout(300);
        check(await page.locator('text=AI 诊室').isVisible(), "Clinic screen header visible");
        check(await page.locator('text=选咨询人').isVisible(), "ProgressStepper step 1 visible");
        check(await page.locator('text=本人').isVisible(), "PatientSelector: self option visible");
        check(await page.locator('text=父亲').isVisible(), "PatientSelector: father option visible");
        await review(page, '03_clinic_step0');

        await page.locator('text=下一步：描述症状').click();
        await page.waitForTimeout(200);
        check(await page.locator('text=拍化验单').isVisible(), "InputMethodPanel: photo option visible");
        check(await page.locator('text=语音描述').isVisible(), "InputMethodPanel: voice option visible");
        await review(page, '04_clinic_step1');

        await page.locator('text=语音描述').click();
        await page.waitForTimeout(200);
        check(await page.locator('text=正在聆听').isVisible(), "Recording state active");
        await page.locator('text=正在聆听').click(); // Finish recording
        await page.waitForTimeout(300);
        check(await page.locator('text=AI 预问诊分析完成').isVisible(), "RecommendationResult card visible");
        check(await page.locator('text=前往预约挂号').isVisible(), "Booking CTA visible");
        await review(page, '05_clinic_step2_result');

        console.log('\n=== Module 03: Insurance Screen ===');
        await page.locator('footer span:has-text("查医保")').first().click();
        check(await page.locator('text=医疗保障管家').isVisible(), "Insurance header visible");
        check(await page.locator('text=国家医保电子凭证').isVisible(), "InsuranceCard: header text visible");
        await review(page, '06_insurance');

        // Toggle balance map
        const toggleBtn = page.locator("button[aria-label='Toggle map balance visibility']");
        check(await toggleBtn.isVisible(), "Balance toggle button visible");
        await toggleBtn.click();
        await page.waitForTimeout(200);
        check(await page.locator('text=2,458.32').isVisible(), "Balance revealed after toggle");
        await review(page, '07_insurance_balance_visible');

        console.log('\n=== Module 04: Pharmacy Screen ===');
        await page.locator('footer span:has-text("药管家")').first().click();
        // Pharmacy header text
        check(await page.locator('text=药管家').first().isVisible(), "Pharmacy header visible");
        check(await page.locator('text=拍药盒').isVisible(), "VisualEngineGrid: photo box option visible");
        check(await page.locator('text=扫追溯码').isVisible(), "VisualEngineGrid: trace code option visible");
        check(await page.locator('text=近期用药提醒').isVisible(), "ReminderSection header visible");
        check(await page.locator('text=阿莫西林克拉维酸钾').isVisible(), "ReminderCard: medicine name visible");
        await review(page, '08_pharmacy');

        await page.locator('text=去服用').click();
        await page.waitForTimeout(300);
        check(await page.locator('text=已打卡').isVisible(), "ReminderCard: toggles successfully to Med Taken");
        await review(page, '09_pharmacy_med_taken');

        console.log('\n=== Module 05: Dashboard Screen ===');
        await page.locator('footer span:has-text("健康")').first().click();
        check(await page.locator('h2:has-text(\"健康小目标\")').isVisible(), "Dashboard header visible");
        check(await page.locator('text=今日数据看板').isVisible(), "VitalsHero section visible");
        check(await page.locator('text=每日打卡计划').isVisible(), "HabitList header visible");
        check(await page.locator('text=72').isVisible(), "VitalCard: heart rate visible");
        await review(page, '10_dashboard');

        console.log('\n=== Module 06: Services Screen ===');
        await page.locator('footer span:has-text("就医")').first().click();
        check(await page.locator('h2:has-text(\"就医服务\")').isVisible(), "Services header visible");
        check(await page.locator('text=智能导诊与挂号').isVisible(), "SearchHeader visible");
        check(await page.locator('text=预约挂号').isVisible(), "BookingActionGrid: booking button visible");
        check(await page.locator('text=推荐医疗机构 (北京)').isVisible(), "HospitalList header visible");
        await review(page, '11_services');

        console.log('\n=== Module 07: Report Screen ===');
        await page.locator('footer span:has-text("报告")').first().click();
        check(await page.locator('h2:has-text(\"检查报告夹\")').isVisible(), "Report screen header visible");
        check(await page.locator('text=拍照上传新报告').isVisible(), "UploadHero visible");
        check(await page.locator('text=历史报告记录').isVisible(), "ReportList header visible");
        await review(page, '12_report');

        await browser.close();

        console.log(`\n=== SUMMARY: ${errors.length} FAILURES ===`);
        if (errors.length) {
            errors.forEach(e => console.log(`  ❌ ${e}`));
            process.exit(1);
        } else {
            console.log('  ✅ All UI interactions and checks passed gracefully!');
            process.exit(0);
        }
    } catch (error) {
        console.error('Test script crashed:', error);
        process.exit(1);
    }
})();
