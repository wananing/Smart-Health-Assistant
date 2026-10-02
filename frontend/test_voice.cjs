/*
 * Drives the voice clinic call screen against mock_voice_server.cjs.
 *
 *   node mock_voice_server.cjs &
 *   VITE_VOICE_WS_URL=ws://localhost:8765/api/voice npm run dev &
 *   node test_voice.cjs            # BASE_URL / MOCK_URL override the defaults
 *
 * DEVICE picks the Playwright device profile (default "iPhone 13"; "iPhone 8"
 * is 375×667). Screenshots of every call state go to $SHOTS_DIR (default:
 * <tmpdir>/voice-shots), and each one also gets a layout check (header not
 * overlapped, no horizontal scroll, current caption not clipped).
 *
 * Chromium's fake audio device stands in for the microphone, so capture and
 * the uplink framing are exercised; echo cancellation, real speakers and iOS
 * Safari are not.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium, devices } = require('playwright');

const BASE_URL = process.env.BASE_URL || 'http://localhost:5173';
const MOCK_URL = process.env.MOCK_URL || 'http://localhost:8765';
const DEVICE = process.env.DEVICE || 'iPhone 13';
const SHOTS = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'voice-shots');

const results = [];
const check = (name, ok, detail = '') => {
    results.push({ name, ok });
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`);
};

const setScenario = (name) => fetch(`${MOCK_URL}/scenario/${name}`).then(r => r.json());
const mockStats = () => fetch(`${MOCK_URL}/stats`).then(r => r.json());

/** Record every distinct value of the call-state attribute, so short states are not missed. */
const STATE_RECORDER = () => {
    window.__callStates = [];
    setInterval(() => {
        const el = document.querySelector('[data-call-state]');
        const value = el ? el.getAttribute('data-call-state') : null;
        const list = window.__callStates;
        if (value && list[list.length - 1] !== value) list.push(value);
    }, 40);
};

const newPage = async (browser, extra = {}) => {
    const context = await browser.newContext({ ...devices[DEVICE], permissions: ['microphone'], ...extra });
    await context.addInitScript(STATE_RECORDER);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    await page.goto(BASE_URL);
    return { context, page, errors };
};

/** Geometry problems that a screenshot would show: overlap, sideways scroll, clipped caption. */
const layoutProblems = (page) => page.evaluate(() => {
    const problems = [];
    const root = document.querySelector('[data-testid="voice-call"]');
    if (!root) return problems;
    if (root.scrollWidth > root.clientWidth + 1 || document.documentElement.scrollWidth > window.innerWidth + 1) {
        problems.push('horizontal overflow');
    }
    const header = root.querySelector('header');
    const orb = root.querySelector('[data-call-state]');
    if (header && orb && orb.getBoundingClientRect().top < header.getBoundingClientRect().bottom - 1) {
        problems.push('orb overlaps header');
    }
    const caption = root.querySelector('[data-testid="current-caption"]');
    if (caption) {
        const box = caption.getBoundingClientRect();
        if (box.height < 40) problems.push(`caption area only ${Math.round(box.height)}px`);
        if (caption.scrollHeight > caption.clientHeight + 1) problems.push('caption needs scrolling');
    }
    if (root.scrollTop !== 0) problems.push(`call screen scrolled by ${root.scrollTop}px`);
    const footer = root.querySelector('footer');
    if (footer && footer.getBoundingClientRect().bottom > window.innerHeight + 1) problems.push('controls off-screen');
    const pinned = root.querySelector('[data-testid="pinned-cards"]');
    if (pinned && pinned.scrollHeight > pinned.clientHeight + 1) problems.push('pinned cards clipped');
    for (const el of root.querySelectorAll('button')) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && (r.left < -1 || r.right > window.innerWidth + 1)) problems.push(`button off-screen: ${el.textContent.trim().slice(0, 10)}`);
    }
    return problems;
});

const shot = async (page, name) => {
    await page.waitForTimeout(250); // let the 150–300 ms transitions settle
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
    const problems = await layoutProblems(page);
    check(`layout ok: ${name}`, problems.length === 0, problems.join('; '));
};

const caption = (page) => page.getByTestId('current-caption');
const transcriptUser = (page, text) => page.locator('[data-caption-role="user"]', { hasText: text });

const normalCall = async (browser) => {
    console.log('\n── normal call (clinic header entry) ──');
    await setScenario('normal');
    const { context, page, errors } = await newPage(browser);

    await page.getByRole('button', { name: 'AI诊室' }).click();
    await page.getByTitle('语音问诊', { exact: true }).click();
    await page.getByRole('button', { name: '同意并开始' }).waitFor();
    check('first-use consent notice shown', await page.getByText('第三方语音服务商').isVisible());
    await page.screenshot({ path: path.join(SHOTS, '01-consent.png') });
    await page.getByRole('button', { name: '同意并开始' }).click();

    await caption(page).getByText('您好，请说说哪里不舒服。').waitFor({ timeout: 10_000 });
    check('opening sentence is the current caption', true);
    await page.locator('[data-call-state="listening"]').waitFor({ timeout: 10_000 });
    await shot(page, '02-listening');

    await page.locator('[data-testid="current-caption"][data-speaker="user"][data-final="false"]').waitFor({ timeout: 10_000 });
    check('user partial shown as the current caption', true);
    await page.screenshot({ path: path.join(SHOTS, '03-user-partial.png') });
    await page.locator('[data-call-state="thinking"]').waitFor({ timeout: 10_000 });
    await shot(page, '04-thinking');
    check('partial replaced by the final', await transcriptUser(page, '我头疼').count() === 1
        && await page.locator('[data-caption-role="user"][data-caption-final="true"]', { hasText: '我头疼，已经三天了' }).count() === 1);

    await page.locator('[data-fact="chief_complaint"][data-filled="true"]').waitFor();
    check('facts card lights chief_complaint and duration',
        await page.locator('[data-fact="duration"][data-filled="true"]').count() === 1);
    await page.locator('[data-call-state="speaking"]').waitFor({ timeout: 10_000 });
    await caption(page).getByText('疼得厉害吗').waitFor();
    check('spoken follow-up is the current caption, shown once on the main screen',
        await page.getByText('疼得厉害吗？是一跳一跳地疼，还是一直胀着疼？').locator('visible=true').count() === 1);
    await shot(page, '05-speaking');

    await page.getByRole('button', { name: '对，继续' }).waitFor({ timeout: 20_000 });
    check('confirm buttons shown in the facts card', await page.getByRole('button', { name: '我要改' }).isVisible());
    await shot(page, '06-confirm');
    await page.getByRole('button', { name: '我要改' }).click();
    const dialog = page.getByRole('dialog', { name: '修改症状要点' });
    await dialog.waitFor();
    check('我要改 opens the editor directly', true);
    await dialog.locator('[data-edit-field="location"]').click();
    await dialog.locator('textarea').fill('额头');
    await page.waitForTimeout(300); // tab colour transition
    await page.screenshot({ path: path.join(SHOTS, '07-edit-sheet.png') });
    await dialog.getByRole('button', { name: '保存' }).click();
    await page.locator('[data-fact="location"][data-filled="true"]', { hasText: '额头' }).waitFor();
    check('edit_fact updates the facts card', true);
    await transcriptUser(page, '更正一下，部位是额头').waitFor({ state: 'attached', timeout: 5000 });
    check('edit_fact echoed as a stt.final caption', true);
    await page.getByRole('button', { name: '对，继续' }).click();
    // Transcript entries read "<speaker label><text>", so the echoed tap is "您对".
    await page.locator('[data-caption-role="user"]').filter({ hasText: /^您对$/ }).waitFor({ state: 'attached', timeout: 5000 });
    check('confirm tap echoed as a "对" caption', true);

    await caption(page).getByText('根据您的描述，建议尽快到神经内科就诊。').waitFor({ timeout: 15_000 });
    check('conclusion\'s first sentence is spoken before the card arrives',
        await page.getByTestId('conclusion-card').count() === 0);
    await page.getByTestId('conclusion-card').waitFor({ timeout: 15_000 });
    check('conclusion card surfaces on the main screen', await page.getByTestId('conclusion-card').isVisible());
    await shot(page, '08-conclusion');

    // Barge in while the rest of the conclusion is spoken: typing counts as input.
    await page.locator('[data-call-state="speaking"]').waitFor({ timeout: 10_000 });
    await page.getByRole('button', { name: '打字' }).click();
    await page.getByPlaceholder('打字描述症状…').fill('好的，谢谢');
    await page.getByRole('button', { name: '发送' }).click();
    await page.waitForTimeout(1200);
    check('typed text appears exactly once (stt.final only)', await transcriptUser(page, '好的，谢谢').count() === 1);

    await page.getByTestId('open-transcript').click();
    await page.locator('[data-testid="transcript-sheet"][data-open="true"]').waitFor();
    await page.locator('[data-card="clinic_recommendation"]').first().waitFor();
    check('transcript sheet shows the full record and cards', await page.getByTestId('transcript-sheet').getByText('我头疼，已经三天了').isVisible());
    await page.screenshot({ path: path.join(SHOTS, '09-transcript-sheet.png') });
    await page.getByRole('button', { name: '收起通话记录' }).click();

    const states = await page.evaluate(() => window.__callStates);
    check('state sequence covers connecting/listening/thinking/speaking',
        ['connecting', 'listening', 'thinking', 'speaking'].every(s => states.includes(s)), states.join(' > '));

    await page.getByRole('button', { name: '挂断' }).click();
    await page.locator('[data-card="clinic_summary"]').waitFor({ timeout: 10_000 });
    check('summary card merged into chat after hang-up', true);
    check('call screen closed', await page.locator('[data-testid="voice-call"]').count() === 0);
    check('final captions merged into chat', await page.getByText('我头疼，已经三天了').count() > 0);
    check('chat stays in clinic mode', await page.getByText('AI 诊室', { exact: true }).count() > 0);
    const summary = page.locator('[data-card="clinic_summary"]');
    check('summary shows duration, facts and disclaimer',
        await summary.getByText('通话时长').count() === 1
        && await summary.getByText('额头').count() === 1
        && await summary.getByText('以上为 AI 预问诊整理').count() === 1
        && await summary.getByText('已完成').count() === 1);
    check('summary has no emergency block without flags', await summary.getByText('危险信号').count() === 0);
    await summary.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(SHOTS, '10-chat-summary.png') });

    const stats = await mockStats();
    check('hello reports caps', Boolean(stats.hello && stats.hello.caps && stats.hello.caps.sample_rate === 16000 && stats.hello.caps.playback_receipts === true),
        JSON.stringify(stats.hello && stats.hello.caps));
    check('uplink frames are 8+640 bytes with contiguous seq/sample_offset',
        stats.uplinkFrames > 50 && stats.uplinkBadSize === 0 && stats.uplinkSeqGaps === 0 && stats.uplinkOffsetErrors === 0,
        `frames=${stats.uplinkFrames} nonSilent=${stats.uplinkNonSilentFrames}`);
    const started = stats.receipts.filter(r => r.type === 'playback.started').length;
    const ended = stats.receipts.filter(r => r.type === 'playback.ended').length;
    const interrupted = stats.receipts.filter(r => r.type === 'playback.interrupted');
    check('playback receipts sent', started > 0 && ended > 0, `started=${started} ended=${ended} interrupted=${interrupted.length}`);
    check('tts.stop answered with playback.interrupted + played_ms',
        stats.stops.length > 0 && stats.stops.every(s => s.receipt && typeof s.receipt.played_ms === 'number'),
        JSON.stringify(stats.stops));
    // The mock sends one more chunk of each stopped turn after tts.stop; it must never play.
    const afterStop = stats.stops.flatMap(stop => {
        const idx = stats.receipts.findIndex(r => r.type === 'playback.interrupted' && r.turn_id === stop.turn_id);
        return stats.receipts.slice(idx + 1).filter(r => r.turn_id === stop.turn_id);
    });
    check('late audio of a stopped turn is dropped (no receipts after the stop)', afterStop.length === 0);
    check('controls sent', ['ui.action:edit_fact', 'ui.action:confirm', 'input.text', 'bye'].every(c => stats.controls.includes(c)), stats.controls.join(','));
    check('no page errors', errors.length === 0, errors.join(' | '));
    await context.close();
};

const emergencyCall = async (browser) => {
    console.log('\n── emergency call (elder mode home entry) ──');
    await setScenario('emergency');
    const { context, page, errors } = await newPage(browser);
    await page.getByRole('switch', { name: /长辈模式/ }).click();
    await page.getByRole('button', { name: /语音问诊/ }).first().click();
    await page.getByRole('button', { name: '同意并开始' }).click();
    await page.getByRole('button', { name: '说完了' }).waitFor();
    await page.locator('[data-call-state="listening"]').waitFor({ timeout: 10_000 });
    await shot(page, '11-elder-listening');
    check('elder mode: 说完了 always enabled', await page.getByRole('button', { name: '说完了' }).isEnabled());

    const dialog = page.getByRole('alertdialog');
    await dialog.waitFor({ timeout: 15_000 });
    check('emergency takeover shown', true);
    check('tel:120 link, no auto-dial', await dialog.locator('a[href="tel:120"]').count() === 1);
    check('tel:120 visible without scrolling', await dialog.locator('a[href="tel:120"]').isVisible()
        && await dialog.locator('a[href="tel:120"]').evaluate(el => el.getBoundingClientRect().bottom <= window.innerHeight));
    check('danger signals from the card shown', await dialog.getByText('胸口剧痛伴呼吸困难').count() === 1);
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(SHOTS, '12-emergency.png') });
    check('emergency details fit without scrolling', await dialog.evaluate(el => {
        const details = el.firstElementChild;
        return details.scrollHeight <= details.clientHeight + 1;
    }));
    await dialog.getByRole('button', { name: '我没事，继续问诊' }).click();
    check('takeover dismissed by tap', await page.getByRole('alertdialog').count() === 0);
    await caption(page).getByText('好的，我们继续').waitFor({ timeout: 10_000 });
    await shot(page, '13-elder-speaking');
    await page.getByRole('button', { name: '挂断' }).click();
    await page.locator('[data-card="clinic_summary"]').waitFor({ timeout: 10_000 });
    check('summary after emergency call', await page.getByText('请立即就医').count() > 0);
    check('summary shows the emergency flags',
        await page.locator('[data-card="clinic_summary"]').getByText('通话中识别到的危险信号').count() === 1
        && await page.locator('[data-card="clinic_summary"]').getByText('呼吸困难').count() > 0);

    const stats = await mockStats();
    check('elder_mode sent in hello user_info', stats.hello && stats.hello.user_info && stats.hello.user_info.elder_mode === true);
    check('emergency_dismiss sent', stats.controls.includes('ui.action:emergency_dismiss'));
    check('no page errors', errors.length === 0, errors.join(' | '));
    await context.close();
};

const droppedCall = async (browser) => {
    console.log('\n── dropped socket (reconnect with thread_id) ──');
    await setScenario('drop');
    const { context, page, errors } = await newPage(browser);
    await page.getByRole('button', { name: 'AI诊室' }).click();
    await page.getByTitle('语音问诊', { exact: true }).click();
    await page.getByRole('button', { name: '同意并开始' }).click();
    await page.getByText('重连中').waitFor({ timeout: 20_000 });
    check('reconnecting shown after the drop', true);
    await shot(page, '14-reconnecting');
    await page.getByText('已连接').waitFor({ timeout: 10_000 });
    const stats = await mockStats();
    check('reconnect hello carries the thread_id', Boolean(stats.hello && stats.hello.thread_id && stats.hello.thread_id.startsWith('mock-')), stats.hello && stats.hello.thread_id);
    await page.getByRole('button', { name: '对，继续' }).waitFor({ timeout: 20_000 });
    check('call resumes to the confirm step', true);
    check('captions survive the reconnect', await transcriptUser(page, '我头疼，已经三天了').count() > 0);
    const states = await page.evaluate(() => window.__callStates);
    check('error state shown while reconnecting', states.includes('error'), states.join(' > '));
    await page.getByRole('button', { name: '挂断' }).click();
    await page.locator('[data-card="clinic_summary"]').waitFor({ timeout: 10_000 });
    check('no page errors', errors.length === 0, errors.join(' | '));
    await context.close();
};

const pushToTalkCall = async (browser) => {
    console.log('\n── manual turn-end (degraded + push_to_talk) ──');
    await setScenario('ptt');
    // This scenario also runs with reduced motion, to check every animation is switched off.
    const { context, page, errors } = await newPage(browser, { reducedMotion: 'reduce' });
    await page.getByRole('button', { name: 'AI诊室' }).click();
    await page.getByTitle('语音问诊', { exact: true }).click();
    await page.getByRole('button', { name: '同意并开始' }).click();
    await page.getByTestId('push-to-talk-hint').waitFor({ timeout: 10_000 });
    check('push_to_talk notice shown', await page.getByText('识别不太顺利').count() > 0);
    check('no TTS-outage banner for push_to_talk', await page.getByText('语音播报暂不可用').count() === 0);
    const endTurn = page.getByRole('button', { name: '说完了' });
    await page.locator('[data-call-state="listening"]').waitFor({ timeout: 10_000 });
    await page.waitForTimeout(300);
    check('说完了 enabled and emphasised while listening',
        await endTurn.isEnabled() && await endTurn.getAttribute('data-emphasized') === 'true');
    await shot(page, '15-push-to-talk');
    const running = await page.evaluate(() => document.getAnimations()
        .filter(a => a instanceof CSSAnimation && a.playState === 'running')
        .map(a => a.animationName));
    check('prefers-reduced-motion: no running CSS animations', running.length === 0, running.join(','));
    await page.waitForTimeout(2500);
    check('no automatic commit without 说完了', await page.locator('[data-caption-role="user"]').count() === 0);
    await endTurn.click();
    await page.locator('[data-caption-role="user"][data-caption-final="true"]', { hasText: '我头疼，已经三天了' }).waitFor({ state: 'attached', timeout: 5000 });
    check('说完了 commits the turn', true);
    await page.locator('[data-call-state="speaking"]').waitFor({ timeout: 10_000 });
    await page.waitForTimeout(300);
    check('disabled 说完了 while the assistant speaks', !(await endTurn.isEnabled()));
    await shot(page, '16-endturn-disabled');
    await page.getByRole('button', { name: '挂断' }).click();
    await page.locator('[data-card="clinic_summary"]').waitFor({ timeout: 10_000 });
    check('incomplete summary after early hang-up', await page.locator('[data-card="clinic_summary"]').getByText('未完成').count() === 1);
    const stats = await mockStats();
    check('turn.end sent', stats.controls.includes('turn.end'));
    check('no page errors', errors.length === 0, errors.join(' | '));
    await context.close();
};

(async () => {
    fs.mkdirSync(SHOTS, { recursive: true });
    console.log(`device: ${DEVICE}  shots: ${SHOTS}`);
    const browser = await chromium.launch({
        headless: true,
        args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'],
    });
    try {
        await normalCall(browser);
        await emergencyCall(browser);
        await droppedCall(browser);
        await pushToTalkCall(browser);
    } catch (err) {
        check('scenario completed', false, err.message.split('\n')[0]);
    } finally {
        await browser.close();
    }
    const failed = results.filter(r => !r.ok).length;
    console.log(`\n${results.length - failed}/${results.length} checks passed`);
    process.exit(failed ? 1 : 0);
})();
