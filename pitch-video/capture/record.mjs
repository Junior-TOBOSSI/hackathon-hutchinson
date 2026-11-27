/**
 * Drives the real HOVIS interface (argos-ui, demo data) in Microsoft Edge, like a user would,
 * and saves one sharp screenshot per step plus where the next tap/click happens.
 * Output: public/capture/step-XX.png + public/capture/steps.json (both git-ignored).
 * The Remotion video then plays these steps inside a tablet / laptop frame.
 *
 * Usage (from pitch-video/):  npm run capture
 * Edit the scenario in the STEPS list below: each step = what is on screen, how long,
 * the caption, and optionally what gets clicked next and where the camera zooms.
 */
import { spawn } from 'node:child_process';
import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const here = path.dirname(fileURLToPath(import.meta.url));
const UI_DIR = path.resolve(here, '../../argos-ui');
const OUT_DIR = path.resolve(here, '../public/capture');
const PORT = 4174;
const DEMO_TIME = new Date('2026-11-26T16:51:00');
const BASE = `http://localhost:${PORT}`;

const DEVICES = {
  tablet: { width: 1280, height: 800 }, // operator, at the workstation
  laptop: { width: 1440, height: 900 }, // team leader, AI leader, admin
  tv: { width: 1920, height: 1080 }, // cell TV next to the production line
};

// ---------- helpers used by the scenario ----------
const btn = (name) => (p) => p.getByRole('button', { name });
const tab = (name) => (p) => p.getByRole('tab', { name });
const logout = (p) => p.getByRole('button', { name: 'Se déconnecter' });

/** Hides the developer "Démo" bar: scenario changes must look like real detections. */
async function hideDemoBar(page) {
  await page.evaluate(() => {
    for (const el of document.querySelectorAll('div')) {
      if (el.style.position === 'fixed' && el.textContent?.startsWith('Démo')) el.style.display = 'none';
    }
  });
}

async function operatorScenario(page, scenario) {
  await page.goto(`${BASE}/operateur?scenario=${scenario}`);
  await page.getByRole('button', { name: /SIGNALER/ }).waitFor();
  await hideDemoBar(page);
}

async function login(page, email) {
  const field = page.locator('#ident');
  await field.fill(email);
}

/**
 * The scenario. Fields:
 *  section  optional title card shown before this step (a new role / device)
 *  device   tablet | laptop | tv
 *  caption  short text shown under the device (the speaker says the rest)
 *  hold     seconds this screen stays visible
 *  setup    async (page) => {...} run BEFORE the screenshot (navigation, typing…)
 *  target   (page) => locator clicked AFTER the screenshot (the cursor/finger goes there)
 *  zoom     (page) => locator the camera zooms on during this step
 */
const STEPS = [
  // ---- Operator, on a tablet at the workstation ----
  { section: 'L’opérateur, au poste', device: 'tablet', hold: 7, caption: 'Au poste, l’opérateur se connecte', setup: async (p) => { await p.goto(BASE); await p.locator('#ident').waitFor(); }, target: btn('Se connecter') },
  { device: 'tablet', hold: 13, caption: 'Tout est au vert : pièce conforme, objectif et cadence du shift', setup: async (p) => { await p.getByText('Heure par heure').waitFor(); await hideDemoBar(p); } },
  { device: 'tablet', hold: 9, caption: 'Heure par heure : le surplus d’une heure remplit la suivante', zoom: (p) => p.getByText('Heure par heure').locator('xpath=../..') },
  { device: 'tablet', hold: 13, caption: 'Pièce non conforme : consigne immédiate à l’opérateur', setup: (p) => operatorScenario(p, 'ko'), zoom: (p) => p.locator('section').first() },
  { device: 'tablet', hold: 12, caption: 'EPI manquant : alerte au poste, sans enregistrer de visage', setup: (p) => operatorScenario(p, 'epi') },
  { device: 'tablet', hold: 11, caption: 'Plusieurs écarts : l’écran donne les actions dans l’ordre', setup: (p) => operatorScenario(p, 'multi'), target: btn(/SIGNALER/) },
  { device: 'tablet', hold: 7, caption: 'Un geste pour prévenir le team leader', setup: async (p) => { await p.getByText(/TEAM LEADER PRÉVENU/).waitFor(); await hideDemoBar(p); } },

  // ---- Cell TV, next to the production line ----
  { section: 'La TV de la cellule, au bord de la ligne', device: 'tv', hold: 15, caption: 'Toute l’équipe suit la performance des 12 postes, lisible de loin', setup: async (p) => { await p.goto(`${BASE}/tv/C3`); await p.getByText('Pièces bonnes du shift').waitFor(); } },

  // ---- Team leader, on a laptop ----
  { section: 'Le team leader, depuis son PC', device: 'laptop', hold: 5, caption: 'Le team leader se connecte : il gère les postes de sa cellule', setup: async (p) => { await p.locator('#ident').waitFor(); await login(p, 'c.diaz@hutchinson.com'); }, target: btn('Se connecter') },
  { device: 'laptop', hold: 13, caption: 'Ses 12 postes : état, rythme, pièces KO et alertes en cours', setup: (p) => p.getByRole('tablist').waitFor(), target: (p) => p.getByRole('button', { name: /^Sécurité ·/ }) },
  { device: 'laptop', hold: 8, caption: 'Il filtre : les postes avec un problème de sécurité', setup: (p) => p.waitForTimeout(400), target: (p) => p.getByRole('row', { name: /^Poste P06/ }) },
  { device: 'laptop', hold: 13, caption: 'Il ouvre l’écran du poste : exactement la vue de l’opérateur', setup: async (p) => { await p.getByText(/Vous consultez/).waitFor(); await hideDemoBar(p); }, target: (p) => p.getByRole('button', { name: /Je m’en occupe/ }).first() },
  { device: 'laptop', hold: 7, caption: 'Il prend l’alerte en charge', setup: async (p) => { await p.getByText('Pris en charge').first().waitFor(); await hideDemoBar(p); }, target: (p) => p.getByRole('link', { name: /Ma cellule/ }) },
  { device: 'laptop', hold: 11, caption: 'Production de la cellule : le réel face à l’objectif', setup: (p) => p.getByText('Production de la cellule').waitFor(), zoom: (p) => p.getByText('Production de la cellule').locator('xpath=../..') },
  { device: 'laptop', hold: 4, caption: 'Puis il passe aux alertes de sa cellule', setup: (p) => p.evaluate(() => window.scrollTo(0, 0)), target: tab(/Alertes/) },
  { device: 'laptop', hold: 11, caption: 'Les alertes de la cellule, les prioritaires en premier', setup: (p) => p.waitForTimeout(400), target: (p) => p.getByRole('button', { name: 'Valider' }).first() },
  { device: 'laptop', hold: 6, caption: 'Valider ou rejeter en un clic', setup: (p) => p.waitForTimeout(400), target: (p) => p.getByRole('link', { name: 'Historique' }).first() },
  { device: 'laptop', hold: 10, caption: 'L’historique du shift d’un poste, sans nom ni classement', setup: (p) => p.getByText('Bande du shift').waitFor(), target: logout },

  // ---- AI leader ----
  { section: 'L’AI Leader, garant des modèles', device: 'laptop', hold: 5, caption: 'L’AI Leader pilote les modèles', setup: async (p) => { await p.locator('#ident').waitFor(); await login(p, 'a.noui@hutchinson.com'); }, target: btn('Se connecter') },
  { device: 'laptop', hold: 13, caption: 'Santé des modèles en production, dérives détectées', setup: (p) => p.getByText('Santé des modèles en production').waitFor(), target: (p) => p.getByRole('button', { name: /Relancer l’entraînement/ }).first() },
  { device: 'laptop', hold: 7, caption: 'Un modèle décroche : on relance son entraînement', setup: (p) => p.getByText('Entraînement relancé.').waitFor(), target: btn('Promouvoir en production') },
  { device: 'laptop', hold: 8, caption: 'La nouvelle version est validée puis promue en production', setup: (p) => p.getByText(/promu en production/).waitFor(), target: logout },

  // ---- Admin ----
  { section: 'L’administrateur, gardien des accès', device: 'laptop', hold: 5, caption: 'L’administrateur gère les accès', setup: async (p) => { await p.locator('#ident').waitFor(); await login(p, 'admin@hutchinson.com'); }, target: btn('Se connecter') },
  { device: 'laptop', hold: 10, caption: 'Comptes, rôles et périmètres de chacun', setup: (p) => p.getByRole('tablist').waitFor(), target: btn('+ Ajouter un utilisateur') },
  { device: 'laptop', hold: 7, caption: 'Ajouter un utilisateur en quelques secondes', setup: (p) => p.waitForTimeout(400), target: tab(/Rôles et droits/) },
  { device: 'laptop', hold: 10, caption: 'Chaque rôle ne voit que ce qui le concerne', setup: (p) => p.waitForTimeout(400), target: tab(/Journal/) },
  { device: 'laptop', hold: 8, caption: 'Chaque action est tracée dans le journal', setup: (p) => p.waitForTimeout(400) },
];

// ---------- runner ----------
function startPreview() {
  const proc = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], { cwd: UI_DIR, shell: true, stdio: 'ignore' });
  return proc;
}

async function waitForServer() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(BASE);
      if (res.ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`argos-ui preview did not start on ${BASE} (run "npm run build" in argos-ui first)`);
}

const center = (b) => (b ? { x: b.x + b.width / 2, y: b.y + b.height / 2 } : null);
const rect = (b) => (b ? { x: b.x, y: b.y, width: b.width, height: b.height } : null);

async function main() {
  // Keep steps.json in place while capturing (a running Studio would fail without it);
  // only old screenshots are removed, and steps.json is replaced at the very end.
  mkdirSync(OUT_DIR, { recursive: true });
  for (const f of readdirSync(OUT_DIR)) if (f.endsWith('.png')) rmSync(path.join(OUT_DIR, f));

  const server = startPreview();
  try {
    await waitForServer();
    const browser = await chromium.launch({ channel: 'msedge' });
    const contexts = {};
    const pages = {};
    for (const [name, size] of Object.entries(DEVICES)) {
      // Double resolution for the tablet and laptop (shown large in the video); the TV is already 1920 × 1080.
      contexts[name] = await browser.newContext({ viewport: size, deviceScaleFactor: name === 'tv' ? 1 : 2, locale: 'fr-FR', hasTouch: name === 'tablet' });
      // Same clock on every screen, matching the demo data (shift B, 16:51).
      await contexts[name].clock.setFixedTime(DEMO_TIME);
      pages[name] = await contexts[name].newPage();
    }
    // The laptop starts on the login page, logged out.
    await pages.laptop.goto(BASE);

    const out = [];
    for (const [i, step] of STEPS.entries()) {
      const page = pages[step.device];
      if (step.setup) await step.setup(page);
      await page.waitForTimeout(500); // let charts and transitions settle

      const target = step.target ? step.target(page) : null;
      if (target) await target.scrollIntoViewIfNeeded();
      const zoom = step.zoom ? step.zoom(page) : null;
      if (zoom) await zoom.scrollIntoViewIfNeeded();

      const image = `step-${String(i).padStart(2, '0')}.png`;
      await page.screenshot({ path: path.join(OUT_DIR, image) });
      out.push({
        image,
        section: step.section ?? null,
        device: step.device,
        viewport: DEVICES[step.device],
        hold: step.hold,
        caption: step.caption,
        target: target ? center(await target.boundingBox()) : null,
        zoom: zoom ? rect(await zoom.boundingBox()) : null,
      });
      console.log(`step ${i}: ${step.caption}`);

      if (target) await target.click();
    }

    writeFileSync(path.join(OUT_DIR, 'steps.json'), JSON.stringify(out, null, 2));
    await browser.close();
    console.log(`\n${out.length} steps saved to ${OUT_DIR}`);
  } finally {
    // shell: true on Windows wraps vite in a shell: kill the whole process tree.
    if (process.platform === 'win32') spawn('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
    else server.kill();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
