// Records one H.264 MP4 per scene off the live site with the fake cursor
// injected (quality-100 screencast JPEG frames assembled via the ffmpeg
// concat demuxer), and writes trim markers to ../src/manifest.json.
// Usage (from promo/): node capture/record-scenes.mjs [scene ...]
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

export const BASE = 'https://www.ratemyhusky.com';
const RAW = 'capture/raw';
const CLIPS = 'public/clips';
const MANIFEST = fileURLToPath(new URL('../src/manifest.json', import.meta.url));
const cursorSrc = readFileSync(
  fileURLToPath(new URL('./cursor.js', import.meta.url)),
  'utf8'
);

export async function newScene(browser) {
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2, // 4K framebuffer; screencast downsamples -> crisp 1080p
  });
  await context.addInitScript(cursorSrc);
  await context.addInitScript(() => {
    localStorage.setItem('prof_course_tip_dismissed', '1');
  });
  const page = await context.newPage();
  const scene = { context, page, rec0: 0, frames: [] };
  // Quality-100 JPEG frames, bypassing recordVideo's hardcoded 1 Mbps VP8.
  await page.screencast.start({
    quality: 100,
    size: { width: 1920, height: 1080 },
    onFrame: (frame) => {
      if (scene.frames.length === 0) scene.rec0 = Date.now();
      scene.frames.push({ data: frame.data, timestamp: frame.timestamp });
    },
  });
  return scene;
}

// Seconds since the recording (page) started — used for trim markers.
export const mark = (scene) => (Date.now() - scene.rec0) / 1000;

export async function glideClick(page, selector, ms = 700) {
  const el = page.locator(selector).first();
  await el.waitFor({ state: 'visible' });
  const box = await el.boundingBox();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.evaluate(
    ([x, y, ms]) => window.__cursor.moveTo(x, y, ms),
    [x, y, ms]
  );
  await page.waitForTimeout(120 + Math.random() * 130); // human settle before click
  await page.evaluate(() => window.__cursor.pulse());
  await page.mouse.click(x, y);
}

export function probeDuration(file) {
  return parseFloat(
    execFileSync('ffprobe', [
      '-v', 'error',
      '-show_entries', 'format=duration',
      '-of', 'csv=p=0',
      file,
    ]).toString()
  );
}

export async function saveScene(scene, name, markers = {}) {
  await scene.page.screencast.stop();
  const stopWall = Date.now();
  await scene.context.close();
  const { frames, rec0 } = scene;
  if (frames.length === 0) throw new Error(`no frames captured for ${name}`);
  const dir = `${RAW}/${name}`;
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  // onFrame timestamps are epoch milliseconds: Playwright converts CDP's
  // metadata.timestamp (seconds) via *1000 before dispatching frames
  // (playwright-core 1.61 coreBundle.js, screencastFrame dispatch).
  const ts = frames.map((f) => f.timestamp);
  const lines = ['ffconcat version 1.0'];
  frames.forEach((f, i) => {
    const file = `f${String(i).padStart(5, '0')}.jpg`;
    writeFileSync(`${dir}/${file}`, f.data);
    // Screencast only emits on change: hold each frame until the next one
    // (last frame holds until stop time, measured on the wall clock).
    const dur =
      i + 1 < frames.length
        ? (ts[i + 1] - ts[i]) / 1000
        : (stopWall - rec0) / 1000 - (ts[i] - ts[0]) / 1000;
    lines.push(`file ${file}`, `duration ${Math.max(dur, 1 / 120).toFixed(6)}`);
  });
  // concat demuxer quirk: repeat the last file so its duration is honored.
  lines.push(`file f${String(frames.length - 1).padStart(5, '0')}.jpg`);
  writeFileSync(`${dir}/frames.ffconcat`, lines.join('\n') + '\n');
  // Clips stay full-range (ffmpeg keeps the JPEG range despite -pix_fmt
  // yuv420p); that's fine for intermediates — the final render normalizes
  // to bt709 limited via Config.setColorSpace in remotion.config.ts.
  execFileSync(
    'ffmpeg',
    ['-y', '-f', 'concat', '-i', `${dir}/frames.ffconcat`,
     '-vf', 'fps=30', '-c:v', 'libx264', '-crf', '16', '-preset', 'slow',
     '-pix_fmt', 'yuv420p', '-an', resolve(CLIPS, `${name}.mp4`)],
    { stdio: 'inherit' }
  );
  return { file: `clips/${name}.mp4`, markers };
}

/* ---------------- scenes ---------------- */

async function sceneSmoke(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(500);
  await page.evaluate(() => window.__cursor.moveTo(400, 300, 900));
  await page.evaluate(() => window.__cursor.moveTo(1400, 700, 900));
  await page.evaluate(() => window.__cursor.scrollTo(600, 1000));
  await page.waitForTimeout(500);
  return saveScene(s, 'smoke');
}

// Scene 2: homepage search — type "rachlin", suggestions drop down,
// hover the top results. ("machine learning" verified to return [] live.)
async function sceneSearch(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(600);
  await glideClick(page, '.search-input', 800);
  await page.keyboard.type('rachlin', { delay: 70 });
  await page.locator('.search-suggestions .suggestion-item').first().waitFor();
  const suggestionsAt = mark(s);
  await page.waitForTimeout(400);
  const items = page.locator('.suggestion-item');
  const n = Math.min(await items.count(), 3);
  for (let i = 0; i < n; i++) {
    const box = await items.nth(i).boundingBox();
    await page.evaluate(
      ([x, y]) => window.__cursor.moveTo(x, y, 350),
      [box.x + box.width / 2, box.y + box.height / 2]
    );
  }
  await page.waitForTimeout(800);
  return saveScene(s, 'search', { suggestionsAt });
}

// Scene 3: professor page — scroll to the review tabs, flip
// RMP (default) -> Reddit to show both sources.
async function sceneProfessor(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await page.goto(`${BASE}/professors/john-rachlin`, {
    waitUntil: 'networkidle',
  });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(900);
  const tabs = page.locator('.prof-review-tabs');
  await tabs.waitFor();
  const tabsY = await tabs.evaluate(
    (el) => el.getBoundingClientRect().top + window.scrollY
  );
  await page.evaluate(
    ([y]) => window.__cursor.scrollTo(y - 140, 1400),
    [tabsY]
  );
  await page.waitForTimeout(400);
  await glideClick(page, '.prof-review-tabs button:has-text("Reddit")', 500);
  await page.waitForTimeout(1400);
  return saveScene(s, 'professor');
}

// Ask is sign-in gated: inject the user's session token (gitignored file)
// before navigation so it renders. Never log or echo the token.
async function injectAuth(scene) {
  const token = readFileSync(
    fileURLToPath(new URL('./auth-token.txt', import.meta.url)),
    'utf8'
  ).trim();
  // Origin-guarded: init scripts run in every frame, including third-party
  // iframes — the token must only ever land in the site's own localStorage.
  await scene.context.addInitScript(
    (t) => {
      if (location.origin === 'https://www.ratemyhusky.com' || location.origin === 'https://ratemyhusky.com') {
        localStorage.setItem('auth_token', t);
      }
    },
    token
  );
  // Promo cosmetics: the navbar shows the account's first name; show
  // "Husky" with the site's husky icon instead of the real account.
  await scene.context.route('**/api/auth/me', async (route) => {
    const resp = await route.fetch();
    const json = await resp.json();
    json.name = 'Husky';
    json.picture = 'https://www.ratemyhusky.com/logo.jpg';
    await route.fulfill({ response: resp, json });
  });
}

// Scene 4: Ask AI — click the homepage "Try Now" bubble (switches the
// bar to Ask mode and focuses it), type a question, wait for the
// answer. Records the full LLM wait; Remotion jump-cuts typedAt ->
// answerAt. NOTE: fires a real /api/chat question, which has a daily
// limit — do not run this scene in a loop.
async function sceneAsk(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await injectAuth(s);
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(500);
  await glideClick(page, '.home-ask-bubble-trynow', 900);
  await page.waitForTimeout(400);
  await page.keyboard.type('Is John Rachlin a good professor?', {
    delay: 55,
  });
  await page.waitForTimeout(300);
  const typedAt = mark(s);
  await page.keyboard.press('Enter');
  await page.locator('.ask-result').waitFor();
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.ask-result');
      return el && !el.querySelector('.ask-thinking');
    },
    { timeout: 90000 }
  );
  const answerAt = mark(s);
  await page.waitForTimeout(3000); // linger so citations are readable
  return saveScene(s, 'ask', { typedAt, answerAt });
}

// Scene 5: compare — pick Rachlin vs Fontenot, scroll the metrics table.
async function sceneCompare(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await page.goto(`${BASE}/compare`, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(600);
  await glideClick(page, 'input[aria-label="Search left professor"]', 700);
  await page.keyboard.type('rachlin', { delay: 60 });
  await glideClick(page, '.compare-suggestion-list .compare-suggestion', 500);
  await page.waitForTimeout(500);
  await glideClick(page, 'input[aria-label="Search right professor"]', 700);
  await page.keyboard.type('fontenot', { delay: 60 });
  await glideClick(page, '.compare-suggestion-list .compare-suggestion', 500);
  const table = page.locator('.compare-table');
  await table.waitFor();
  await page.waitForTimeout(500);
  const tableY = await table.evaluate(
    (el) => el.getBoundingClientRect().top + window.scrollY
  );
  await page.evaluate(
    ([y]) => window.__cursor.scrollTo(y - 120, 1300),
    [tableY]
  );
  await page.waitForTimeout(1600);
  return saveScene(s, 'compare');
}

// Scene 6: department hub -> course page, scrolled to the Professors panel.
async function sceneCourses(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await page.goto(`${BASE}/departments/computer-science`, {
    waitUntil: 'networkidle',
  });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(900);
  await page.evaluate(() => window.__cursor.scrollTo(500, 1000));
  await page.waitForTimeout(700);
  await page.goto(`${BASE}/courses/CS3500`, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(800);
  const professorsPanel = page.locator('.course-panel:has(h2:text-is("Professors"))');
  await professorsPanel.waitFor();
  const chartY = await professorsPanel.evaluate(
    (el) => el.getBoundingClientRect().top + window.scrollY
  );
  await page.evaluate(
    ([y]) => window.__cursor.scrollTo(y - 120, 1200),
    [chartY]
  );
  await page.waitForTimeout(1400);
  return saveScene(s, 'courses');
}

// Scene 7: dark mode flip on the homepage (floating toggle button).
async function sceneDarkmode(browser) {
  const s = await newScene(browser);
  const { page } = s;
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__cursor.show());
  await page.waitForTimeout(800);
  await glideClick(page, 'button[aria-label="Toggle dark mode"]', 800);
  const toggledAt = mark(s);
  await page.waitForTimeout(2000);
  return saveScene(s, 'darkmode', { toggledAt });
}

export const SCENE_FNS = {
  smoke: sceneSmoke,
  search: sceneSearch,
  professor: sceneProfessor,
  ask: sceneAsk,
  compare: sceneCompare,
  courses: sceneCourses,
  darkmode: sceneDarkmode,
};

/* ---------------- CLI ---------------- */

async function main() {
  // Bare runs skip `smoke` (debug-only) and `ask` (burns a real,
  // daily-limited LLM question) — name them explicitly to run them.
  const names = process.argv.slice(2).length
    ? process.argv.slice(2)
    : Object.keys(SCENE_FNS).filter((n) => n !== 'smoke' && n !== 'ask');
  for (const n of names) {
    if (!SCENE_FNS[n]) throw new Error(`unknown scene: ${n}`);
  }
  mkdirSync(RAW, { recursive: true });
  mkdirSync(CLIPS, { recursive: true });
  const browser = await chromium.launch();
  // Warm up the backend so the first scene doesn't record a cold start.
  const warm = await browser.newPage();
  await warm.goto(`${BASE}/api/stats`, { timeout: 60000 });
  await warm.close();
  let manifest = { scenes: {} };
  try {
    manifest = JSON.parse(readFileSync(MANIFEST, 'utf8'));
  } catch {}
  for (const name of names) {
    console.log(`recording scene: ${name}`);
    const entry = await SCENE_FNS[name](browser);
    entry.durationSec = probeDuration(`${CLIPS}/${name}.mp4`);
    manifest.scenes[name] = entry;
    writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2));
    console.log(`  -> ${entry.file} (${entry.durationSec.toFixed(1)}s)`);
  }
  await browser.close();
}

main();
