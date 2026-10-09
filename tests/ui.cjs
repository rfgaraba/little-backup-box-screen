const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 480, height: 320 }, deviceScaleFactor: 1 });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  fs.mkdirSync('test-results', { recursive: true });
  let checks = 0;
  async function check(name) {
    await page.screenshot({ path: `test-results/${name}.png` });
    const violations = await page.evaluate(() => {
      const result = [];
      for (const e of [document.documentElement, document.body, ...document.querySelectorAll('#screen,main,nav,.card,.list,.actions')]) {
        if (e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1) result.push(`${e.tagName}.${e.className}: overflow`);
      }
      for (const e of document.querySelectorAll('button,h1,p,progress')) {
        const r = e.getBoundingClientRect();
        if (r.top < 0 || r.left < 0 || r.bottom > 320.5 || r.right > 480.5) result.push(`${e.textContent}: outside screen`);
        if (e.tagName === 'BUTTON' && r.height < 48) result.push(`${e.textContent}: small target`);
      }
      return result;
    });
    assert.deepEqual(violations, [], name); checks++;
  }
  const click = name => page.getByRole('button', { name, exact: true }).click();
  const initial = await (await page.request.get('http://127.0.0.1:8080/api/status')).json();
  assert.equal(initial.demo, true, 'Las pruebas UI requieren modo demo');
  assert.notEqual(initial.job.state, 'running', 'Esperar a que termine la simulación anterior');
  await page.request.post('http://127.0.0.1:8080/api/settings', {data:{checksum:true}});
  await page.goto('http://127.0.0.1:8080');
  await page.locator('#mode').getByText('DEMO', {exact:true}).waitFor();
  await check('estado'); await click('Copiar'); await check('origen-1');
  await click('Siguiente'); await check('origen-2'); await click('Anterior');
  await click('Tarjeta SD · ejemplo'); await check('destino');
  await click('Volver al origen'); await check('origen-volver');
  await click('Tarjeta SD · ejemplo'); await click('SSD principal · ejemplo'); await check('confirmar');
  await click('Simular copia'); await page.getByText('Respaldo en curso', { exact: true }).waitFor(); await check('progreso');
  await click('Archivos'); await check('archivos-1');
  await click('Siguiente'); await check('archivos-2');
  await click('Sesión 03'); await check('detalle'); await click('Volver a archivos');
  await click('Siguiente'); await click('Siguiente'); await check('archivos-final');
  await click('Ajustes'); await check('ajustes');
  for (const name of ['Copia', 'Pantalla', 'Sistema']) {
    await click(`${name} ›`); await check(`ajuste-${name}`);
    if (name === 'Copia') { await click('Checksum: activado'); await check('checksum'); }
    await click('Volver a ajustes');
  }
  await click('Copiar'); await page.getByText('Resultado del respaldo', { exact: true }).waitFor(); await check('resultado');
  await click('Nuevo respaldo'); await check('nuevo');
  // Deep folders and unusually long names must fit the same fixed layout.
  await page.route('**/api/files?*', route => route.fulfill({ json: { entries: [{name:'Carpeta con un nombre extremadamente largo de prueba',directory:true,size:null},{name:'otra carpeta',directory:true,size:null}],page:0,pages:3 } }));
  await click('Archivos'); await click('▸ Carpeta con un nombre extremadamente largo de prueba');
  await page.getByRole('heading', {name:'Carpeta con un nombre extremadamente largo de prueba',exact:true}).waitFor();
  await page.getByRole('button', {name:'Subir',exact:true}).waitFor(); await check('carpeta');
  await click('Subir'); await page.getByRole('heading', {name:'Archivos del respaldo',exact:true}).waitFor(); await check('carpeta-subir');
  await page.route('**/api/backup', route => route.fulfill({status:400,json:{error:'El motor no está disponible'}}));
  await click('Copiar'); await click('Tarjeta SD · ejemplo'); await click('SSD principal · ejemplo'); await click('Simular copia');
  await page.getByRole('heading', {name:'No se pudo continuar',exact:true}).waitFor(); await check('error');
  assert.deepEqual(errors, []);
  console.log(`${checks} pantallas verificadas a 480 × 320; sin desbordes ni errores JS.`);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
