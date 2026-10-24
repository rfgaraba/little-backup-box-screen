// Deterministic touch-layout and interaction checks, without Bluetooth or cloud accounts.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

(async () => {
  const status = {demo: false, checksum: true, job: {state: 'idle', message: 'Listo', progress: null}};
  const bluetooth = {available: true, powered: false, connected: false, devices: [
    {id: '/device', name: 'Teclado de prueba', address: '12:34:56:78:90:AB', paired: false, connected: false},
    {id: '/second', name: 'Otro dispositivo', address: '00:00:00:00:00:00', paired: false, connected: false}]};
  const remote = {available: true, enabled: false, target: '', targets: [{id: 'cloud:drive', label: 'Mi Drive', type: 'drive'}]};
  const server = http.createServer((req, res) => {
    const file = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[req.url];
    if (!file) {res.writeHead(404); res.end(); return;}
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(fs.readFileSync(path.join(__dirname, '../web', file)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
    const page = await browser.newPage({viewport: {width: 480, height: 320}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', async route => {
      const req = route.request(), url = new URL(req.url());
      const data = req.method() === 'POST' ? req.postDataJSON() : null;
      let response = {};
      if (url.pathname === '/api/status') response = status;
      if (url.pathname === '/api/devices') response = {sources: [], destinations: []};
      if (url.pathname === '/api/info') response = {wifi: {state: 'connected'}};
      if (url.pathname === '/api/bluetooth') {
        if (data?.action === 'power') bluetooth.powered = data.enabled;
        if (data?.action === 'scan') bluetooth.discovering = true;
        if (data?.action === 'pair') {bluetooth.pairing = '/device'; bluetooth.prompt = {id: 'prompt', device: '/device', kind: 'confirm', code: '000123'};}
        if (data?.action === 'respond') {bluetooth.prompt = null; bluetooth.pairing = null; bluetooth.devices[0].paired = true;}
        if (data?.action === 'connect') {bluetooth.connected = true; bluetooth.devices[0].connected = true;}
        if (data?.action === 'disconnect') {bluetooth.connected = false; bluetooth.devices[0].connected = false;}
        if (data?.action === 'remove') bluetooth.devices[0].paired = false;
        response = data ? status : bluetooth;
      }
      if (url.pathname === '/api/remote') {
        if (data?.action === 'import') remote.targets.push({id: 'cloud:sftp', label: 'SFTP', type: 'sftp'});
        else if (data) Object.assign(remote, data);
        response = data ? status : remote;
      }
      await route.fulfill({json: response});
    });
    fs.mkdirSync('test-results', {recursive: true});
    let checks = 0;
    async function check(name) {
      const violations = await page.evaluate(() => [...document.querySelectorAll('#screen, main, button, h1, p, input')].flatMap(e => {
        const r = e.getBoundingClientRect();
        if (r.bottom > 320.5 || r.right > 480.5 || r.top < 0 || r.left < 0) return [e.textContent + ': outside'];
        if (e.tagName === 'BUTTON' && (r.height < 48 || r.width < 48)) return [e.textContent + ': small'];
        if (e.scrollHeight > e.clientHeight + 1) return [e.textContent + ': overflow'];
        return [];
      }));
      assert.deepEqual(violations, [], name);
      await page.screenshot({path: `test-results/connectivity-${name}.png`}); checks++;
    }
    const click = name => page.getByRole('button', {name, exact: true}).click();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await click('Ajustes'); await check('settings');
    await click('Bluetooth ›'); await check('off');
    await click('Encender'); await check('on');
    await page.locator('#bluetooth-indicator').waitFor({state: 'visible'});
    await click('Buscar'); await check('discovery');
    await click('Teclado de prueba'); await check('device');
    await click('Emparejar'); await check('confirmation');
    await click('Aceptar'); await check('paired');
    await click('Conectar'); assert.equal(bluetooth.connected, true); await check('connected');
    await click('Desconectar');
    page.once('dialog', d => d.accept()); await click('Olvidar'); assert.equal(bluetooth.devices[0].paired, false);
    await click('Dispositivos'); await click('Apagar');
    await page.locator('#bluetooth-indicator').waitFor({state: 'hidden'});
    await click('Volver a ajustes'); await click('Nube ›'); await check('cloud');
    await click('Elegir cuenta'); await check('accounts');
    await click('Mi Drive · drive'); assert.equal(remote.enabled, true); await check('auto-upload');
    await click('Desactivar'); assert.equal(remote.enabled, false);
    await click('Configurar / Importar'); await check('import');
    await page.getByLabel('Importar rclone.conf').setInputFiles({name: 'rclone.conf', mimeType: 'text/plain', buffer: Buffer.from('[sftp]\ntype=sftp\n')});
    await page.getByRole('button', {name: 'SFTP · sftp', exact: true}).waitFor();
    await check('imported');
    assert.deepEqual(errors, []);
    console.log(`${checks} pantallas de Bluetooth/nube verificadas a 480 × 320; flujos y geometría correctos.`);
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(e => {console.error(e); process.exitCode = 1;});
