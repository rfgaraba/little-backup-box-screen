// Exercise polling and selection without a browser or physical storage.
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
  focus() {}
}
const content = new Element('main'), nav = new Element('nav'), mode = new Element('span');
let devices = {sources: [], destinations: [], automatic: {}}, intervals;
let wifi = {available:true, forced:false, state:'CONNECTED', connection:'Hotel', hotspot:'Demo', networks:[]};
const status = {demo:false, checksum:true, job:{state:'idle', progress:null, message:'Listo'}};
const context = vm.createContext({
  document: {querySelector: s => s === '#content' ? content : s === 'nav' ? nav : mode,
    createElement: tag => new Element(tag), querySelectorAll: () => [], activeElement:null},
  fetch: async (url, options) => {
    if (url === '/api/wifi' && options?.body) {
      const action = JSON.parse(options.body).action;
      wifi = {...wifi, forced:action === 'hotspot', state:action === 'hotspot' ? 'HOTSPOT' : 'CONNECTED',
        password:action === 'hotspot' ? 'demo12345678' : '', address:'10.42.0.1/24'};
    }
    return {ok:true, json:async () => url === '/api/devices' ? devices : url === '/api/wifi' ? wifi : status};
  },
  confirm: () => true,
  setInterval: f => { intervals = f; }, console,
});
const buttons = root => root.children.flatMap(e => e.tag === 'button' ? [e] : buttons(e));
const find = name => buttons(content).find(b => b.textContent === name);
(async () => {
  vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(find('Backup').disabled, 'Backup requires both devices');
  assert.ok(find('Seleccionar manual'));
  devices = {sources:[{id:'auto:SD', label:'Tarjeta'}], destinations:[{id:'auto:SSD', label:'Disco'}],
    automatic:{source:'auto:SD', destination:'auto:SSD'}};
  await intervals();
  assert.equal(find('Backup').disabled, false, 'Hotplug enables Backup');
  devices = {sources:[], destinations:devices.destinations, automatic:{destination:'auto:SSD'}};
  await intervals();
  assert.equal(find('Backup').disabled, true, 'Removal disables Backup');
  await find('Seleccionar manual').onclick();
  assert.ok(content.children.some(e => e.textContent === '1 · Elegir origen'));
  await buttons(nav).find(b => b.textContent === 'Ajustes').onclick();
  await find('Wi-Fi ›').onclick();
  await find('Hotspot').onclick();
  assert.ok(find('Volver a Wi-Fi'));
  assert.equal(find('Hotspot').disabled, true);
  await find('Volver a Wi-Fi').onclick();
  assert.ok(find('Conectar red'));
  assert.equal(find('Hotspot').disabled, false);
  console.log('Hotspot manual y vuelta a Wi-Fi verificados.');
  console.log('Inicio en Backup, conexión, desconexión y selección manual verificados.');
})().catch(e => {console.error(e); process.exitCode = 1;});
