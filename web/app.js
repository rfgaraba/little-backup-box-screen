const content = document.querySelector('#content');
const nav = document.querySelector('nav');
let tab = 'Copiar', step = -1, source = null, destination = null, page = 0;
let wifi = {};
let bluetooth = {}, remote = {}, btDevice = null;
function updateBluetoothIndicator() {
  const indicator = document.querySelector('#bluetooth-indicator');
  indicator.hidden = !bluetooth.powered;
  indicator.replaceChildren();
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 22 22'); svg.setAttribute('width', '22'); svg.setAttribute('height', '22');
  const shape = document.createElementNS(svg.namespaceURI, 'path');
  shape.setAttribute('d', 'M10 2 V20 L17 15 L4 6 M10 2 L17 7 L4 16' + (bluetooth.connected ? ' M2 11 H3 M19 11 H20' : ''));
  shape.setAttribute('fill', 'none'); shape.setAttribute('stroke', bluetooth.connected ? '#79dcc6' : '#879bad'); shape.setAttribute('stroke-width', '2');
  svg.append(shape); indicator.append(svg);
  indicator.title = bluetooth.connected ? 'Bluetooth conectado' : 'Bluetooth encendido';
  indicator.setAttribute('aria-label', indicator.title);
}
async function bluetoothAction(action, values = {}) {
  busy = true; render();
  try { await api('/api/bluetooth', {action, ...values}); bluetooth = await api('/api/bluetooth'); updateBluetoothIndicator(); }
  finally { busy = false; }
}
function bluetoothView() {
  const prompt = bluetooth.prompt;
  if (prompt) {
    const device = bluetooth.devices?.find(d => d.id === prompt.device);
    content.append(text('p', device?.name || 'Dispositivo Bluetooth'), text('p', `${prompt.kind === 'display' ? 'Ingresá en el otro dispositivo' : 'Emparejamiento'}: ${prompt.code || 'PIN requerido'}`));
    if (prompt.kind !== 'display') actions(button('Aceptar', async () => {
      let value = '';
      if (['pin', 'passkey'].includes(prompt.kind)) {
        value = await bluetoothCode(prompt.kind);
        if (value === null) return;
      }
      await bluetoothAction('respond', {prompt: prompt.id, accept: true, value});
    }), button('Rechazar', () => bluetoothAction('respond', {prompt: prompt.id, accept: false})));
    else if (bluetooth.pairing) content.append(button('Cancelar', () => bluetoothAction('cancel', {device: bluetooth.pairing})));
  } else if (btDevice) {
    const device = bluetooth.devices?.find(d => d.id === btDevice);
    if (device) {
      content.append(text('p', device.name), text('p', bluetooth.message || device.address, 'hint'));
      const action = device.connected ? 'disconnect' : device.paired ? 'connect' : 'pair';
      const use = button({disconnect: 'Desconectar', connect: 'Conectar', pair: 'Emparejar'}[action], () => bluetoothAction(action, {device: device.id}));
      use.disabled = !!bluetooth.pairing || !!bluetooth.connecting || busy;
      const forget = button(bluetooth.pairing ? 'Cancelar' : 'Olvidar', async () => {
        if (bluetooth.pairing) await bluetoothAction('cancel', {device: bluetooth.pairing});
        else if (confirm(`¿Borrar el emparejamiento de ${device.name}?`)) await bluetoothAction('remove', {device: device.id});
      });
      forget.disabled = busy || (!device.paired && !bluetooth.pairing);
      actions(use, forget);
    } else content.append(text('p', 'Dispositivo no disponible'));
    content.append(button('Dispositivos', () => {btDevice = null;}));
    return;
  } else if (!bluetooth.available) content.append(text('p', bluetooth.message || 'Consultando Bluetooth…'));
  else {
    const power = button(bluetooth.powered ? 'Apagar' : 'Encender', () => bluetoothAction('power', {enabled: !bluetooth.powered}));
    const scan = button(bluetooth.discovering ? 'Buscando…' : 'Buscar', () => bluetoothAction('scan'));
    power.disabled = busy; scan.disabled = busy || !bluetooth.powered || bluetooth.discovering;
    actions(power, scan);
    const list = bluetooth.powered ? bluetooth.devices || [] : [];
    page = Math.min(page, Math.max(0, list.length - 1));
    const device = list[page];
    if (device) content.append(button(device.name + (device.connected ? ' · conectado' : device.paired ? ' · emparejado' : ''), () => {btDevice = device.id;}));
    else content.append(text('p', bluetooth.powered ? 'Poné el dispositivo en modo emparejamiento' : 'Bluetooth apagado', 'hint'));
    if (list.length > 1) {
      const prev = button('Anterior', () => {page--;}); prev.disabled = page === 0;
      const next = button('Siguiente', () => {page++;}); next.disabled = page === list.length - 1;
      actions(button('Volver', () => {setting = null;}), prev, next);
      return;
    }
  }
  content.append(button('Volver a ajustes', () => {setting = null;}));
}
function bluetoothCode(kind) {
  return new Promise(resolve => {
    const dialog = document.createElement('dialog'), form = document.createElement('form'), input = document.createElement('input');
    form.method = 'dialog'; input.placeholder = kind === 'pin' ? 'PIN Bluetooth' : 'Código de hasta 6 dígitos';
    input.setAttribute('aria-label', input.placeholder); input.maxLength = kind === 'pin' ? 16 : 6; input.required = true;
    form.append(input); const accept = document.createElement('button'); accept.textContent = 'Aceptar'; accept.value = 'accept';
    const cancel = document.createElement('button'); cancel.textContent = 'Cancelar'; cancel.value = 'cancel'; cancel.formNoValidate = true;
    form.append(accept, cancel); dialog.append(form); document.body.append(dialog);
    dialog.onclose = () => {resolve(dialog.returnValue === 'accept' ? input.value : null); dialog.remove();}; dialog.showModal(); input.focus();
  });
}
async function saveRemote(enabled, target) {
  await api('/api/remote', {enabled, target}); remote = await api('/api/remote'); setting = 'Nube';
}
function remoteView() {
  if (setting === 'Cuentas') {
    const targets = remote.targets || [];
    page = Math.min(page, Math.max(0, Math.ceil(targets.length / 2) - 1));
    targets.slice(page * 2, page * 2 + 2).forEach(t => content.append(button(`${t.label} · ${t.type}`, () => saveRemote(true, t.id))));
    if (!targets.length) content.append(text('p', 'Configurá una cuenta e importá rclone.conf'));
    if (targets.length > 2) {
      const prev = button('Anterior', () => {page--;}); prev.disabled = page === 0;
      const next = button('Siguiente', () => {page++;}); next.disabled = page >= Math.ceil(targets.length / 2) - 1;
      actions(button('Volver', () => {setting = 'Nube';}), prev, next);
    } else content.append(button('Volver', () => {setting = 'Nube';}));
  } else if (setting === 'Configurar nube') {
    content.append(text('p', 'En tu PC ejecutá rclone config, autorizá Google Drive u otro servicio y elegí su rclone.conf para importarlo.', 'hint'));
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.conf'; input.setAttribute('aria-label', 'Importar rclone.conf');
    input.disabled = status.demo;
    input.onchange = async () => {
      const file = input.files[0]; if (!file) return;
      try {
        if (file.size > 65536) throw Error('Máximo 64 KB');
        await api('/api/remote', {action: 'import', config: await file.text()});
        remote = await api('/api/remote'); setting = 'Cuentas'; page = 0;
      } catch (e) {error = e.message;}
      render();
    };
    content.append(input, text('p', 'También reutiliza las cuentas configuradas en el proyecto oficial. No reemplaza cuentas existentes.', 'hint'));
    content.append(button('Volver', () => {setting = 'Nube';}));
  } else {
    content.append(text('p', `Subida automática: ${remote.enabled ? 'activada' : 'desactivada'} · ${remote.target || remote.message || 'Elegí una cuenta'}`, 'hint truncate'));
    const toggle = button(remote.enabled ? 'Desactivar' : 'Activar', () => saveRemote(!remote.enabled, remote.target || ''));
    const accounts = button('Elegir cuenta', () => {setting = 'Cuentas'; page = 0;});
    toggle.disabled = accounts.disabled = !remote.available;
    actions(toggle, accounts);
    actions(button('Configurar / Importar', () => {setting = 'Configurar nube';}), button('Volver a ajustes', () => {setting = null;}));
  }
}
let wifiTicks = 0;
let info = {};
let monitor = {};
const space = value => value == null ? '—' : `${(Number(value) / 1e9).toFixed(1)} GB`;
function syncSelection() {
  source = devices.sources.find(d => d.id === source?.id && d.available !== false) || devices.sources.find(d => d.id === devices.automatic?.source);
  destination = devices.destinations.find(d => d.id === destination?.id && d.available !== false) || devices.destinations.find(d => d.id === devices.automatic?.destination);
}
async function startBackup() {
  busy = true;
  try { status = await api('/api/backup', {source: source.id, destination: destination.id}); step = 3; }
  finally { busy = false; }
}
async function ejectDevice(device) {
  if (!confirm(`¿Retirar ${device.name || device.label}? Esperá la confirmación antes de desconectarlo.`)) return;
  busy = true; render();
  try { status = await api('/api/remove', {device: device.id}); devices = await api('/api/devices'); }
  finally { busy = false; }
}
function storagePanel(role, device) {
  const panel = document.createElement('div'); panel.className = 'storage-panel';
  const top = document.createElement('div'); top.className = 'storage-top';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 56 48'); svg.setAttribute('aria-hidden', 'true');
  const shape = document.createElementNS(svg.namespaceURI, 'path');
  shape.setAttribute('d', role === 0 ? 'M12 4 H38 L44 10 V43 H12 Z M18 8 V18 M25 8 V18 M32 8 V18' : 'M10 5 H46 V43 H10 Z M15 31 H41 M36 36 H39');
  svg.append(shape);
  const eject = button('⏏', () => ejectDevice(device));
  eject.setAttribute('aria-label', `Retirar ${role === 0 ? 'origen' : 'destino'}`);
  eject.disabled = !device?.disk || busy || status.removing || status.demo;
  top.append(svg, eject); panel.append(top, text('p', role === 0 ? 'ORIGEN' : 'DESTINO', 'hint'));
  panel.append(button(device?.name || device?.label || 'Conectar unidad', () => {step = role; page = 0;}));
  panel.append(text('p', `Usado ${space(device?.used_bytes)}`), text('p', `Libre ${space(device?.free_bytes)}`));
  return panel;
}
function updateWifiIndicator() {
  const indicator = document.querySelector('#wifi-indicator');
  const state = info.wifi?.state || 'unavailable';
  const label = {connected: 'Wi-Fi conectado', connecting: 'Wi-Fi conectando', disconnected: 'Wi-Fi desconectado'}[state] || 'Wi-Fi no disponible';
  const level = info.wifi?.signal == null ? 3 : Math.max(1, Math.min(3, Math.ceil(info.wifi.signal / 33)));
  indicator.replaceChildren();
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 26 22');
  ['M4 8 Q13 0 22 8', 'M7 12 Q13 6 19 12', 'M10 16 Q13 13 16 16', 'M13 19 L13 19.2'].forEach((d, i) => {
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', d); path.setAttribute('stroke', state === 'connected' && (3 - i <= level) ? '#79dcc6' : '#53718d'); svg.append(path);
  });
  if (state !== 'connected') {
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', state === 'connecting' ? 'M23 12 L23 16 M23 19 L23 19.2' : 'M3 2 L23 20');
    path.setAttribute('stroke', '#edf4fa'); svg.append(path);
  }
  indicator.append(svg); indicator.setAttribute('aria-label', label); indicator.title = label;
}
let detail = null, setting = null, path = '', files = { entries: [], page: 0, pages: 1 };
let status = { demo: true, checksum: true, job: { state: 'idle', progress: null, message: 'Conectando…' } };
let devices = { sources: [], destinations: [] }, error = '', busy = false;
async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Error de conexión');
  return data;
}
function button(label, action, cls = '') {
  const b = document.createElement('button'); b.textContent = label; b.className = cls;
  b.onclick = async () => { if (busy) return; try { error = ''; await action(); } catch (e) { error = e.message; } render(); };
  return b;
}
function text(tag, value, cls = '') { const e = document.createElement(tag); e.textContent = value; e.className = cls; return e; }
function card(...lines) { const e = document.createElement('div'); e.className = 'card'; lines.forEach(l => e.append(text('p', l))); return e; }
function wifiCredentials() {
  return new Promise(resolve => {
    const dialog = document.createElement('dialog'), form = document.createElement('form');
    form.method = 'dialog';
    const ssid = document.createElement('input'), password = document.createElement('input');
    ssid.placeholder = 'Red Wi-Fi (SSID)'; ssid.setAttribute('aria-label', 'Red Wi-Fi'); ssid.required = true;
    password.type = 'password'; password.placeholder = 'Contraseña'; password.setAttribute('aria-label', 'Contraseña');
    const list = document.createElement('datalist'); list.id = 'wifi-networks'; ssid.setAttribute('list', list.id);
    wifi.networks.forEach(n => { const option = document.createElement('option'); option.value = n.ssid; list.append(option); });
    const accept = document.createElement('button'); accept.textContent = 'Conectar'; accept.value = 'connect';
    const cancel = document.createElement('button'); cancel.textContent = 'Cancelar'; cancel.type = 'button'; cancel.onclick = () => dialog.close();
    form.append(ssid, password, list, accept, cancel); dialog.append(form); document.body.append(dialog);
    dialog.addEventListener('close', () => { const value = dialog.returnValue === 'connect' ? {ssid:ssid.value, password:password.value} : null; dialog.remove(); resolve(value); });
    dialog.showModal();
  });
}
function actions(...buttons) { const e = document.createElement('div'); e.className = 'actions'; e.append(...buttons); content.append(e); }
function pager(count, onChange, parent) {
  const prev = button('Anterior', () => onChange(page - 1)); prev.disabled = page === 0;
  const next = button('Siguiente', () => onChange(page + 1)); next.disabled = page >= count - 1;
  actions(...(parent ? [button('Subir', parent)] : []), prev, text('span', `${page + 1} / ${count}`), next);
}
async function loadFiles() { files = await api(`/api/files?path=${encodeURIComponent(path)}&page=${page}`); page = files.page; }
function jobView() {
  const job = status.job, running = ['running', 'cancelling'].includes(job.state), metrics = job.metrics;
  content.append(text('h1', running ? job.message : job.state === 'success' ? 'Copia completada con éxito' : job.state === 'error' ? 'Falló el respaldo' : 'Resultado del respaldo', job.state === 'success' ? 'success' : job.state === 'error' ? 'error' : ''));
  const c = card(job.message);
  if (job.progress !== null) { c.prepend(text('div', `${job.progress}%${metrics ? ' · etapa por archivos' : ''}`, metrics ? 'hint' : 'metric')); }
  if (running) { const p = document.createElement('progress'); p.max = 100; if (job.progress !== null) p.value = job.progress; p.setAttribute('aria-label', 'Progreso del respaldo'); c.append(p); }
  content.append(c);
  if (metrics) {
    c.classList.add('transfer-metrics');
    const speed = metrics.write_bps == null ? 'sin datos' : `${(metrics.write_bps / 1000000).toFixed(1)} MB/s`;
    const written = metrics.disk_written_bytes == null ? '' : ` · ${(metrics.disk_written_bytes / 1e9).toFixed(2)} GB`;
    const elapsed = metrics.elapsed_seconds || 0;
    c.append(text('p', `Escritura: ${speed}${written}`), text('p', `Tiempo: ${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}${metrics.eta ? ' · Restante: ' + metrics.eta : ''}`));
    if (metrics.files_total != null) c.append(text('p', `Archivos: ${metrics.files_processed} / ${metrics.files_total}`));
  }
  if (job.state === 'idle') content.append(text('p', status.demo ? 'Probá el flujo sin copiar archivos.' : 'Seleccioná origen y destino configurados.'));
  if (!running) actions(button(['error', 'review', 'cancelled'].includes(job.state) ? 'Reintentar' : 'Nuevo respaldo', () => {tab = 'Copiar'; step = -1; page = 0;}, 'primary'), button('Unidades · retirar', () => {tab = 'Copiar'; step = -1; page = 0;}));
  if (job.state === 'running') content.append(button('Cancelar respaldo', async () => {
    if (!confirm('¿Cancelar el respaldo? Puede quedar un archivo incompleto. Esperá la confirmación antes de retirar dispositivos.')) return;
    status = await api('/api/cancel', {});
  }));
}
function render() {
  document.querySelector('#mode').textContent = status.demo ? 'DEMO' : '';
  updateWifiIndicator();
  nav.replaceChildren(...['Respaldo', 'Utilidades', 'Ajustes'].map(name => {
    const b = button(name, async () => { tab = name === 'Respaldo' ? 'Copiar' : name; detail = setting = null; page = 0; });
    if ((name === 'Respaldo' && tab === 'Copiar') || name === tab || (name === 'Utilidades' && tab === 'Archivos')) b.setAttribute('aria-current', 'page'); return b;
  }));
  content.replaceChildren();
  if (status.shutting_down) {content.append(text('h1', 'Apagando el equipo…'), card('Esperá a que termine antes de quitar la alimentación.')); return;}
  if (error) { content.append(text('h1', 'No se pudo continuar'), card(error)); content.append(button('Volver', () => { error = ''; }, 'primary')); return; }
  if (tab === 'Estado') return jobView();
  if (tab === 'Copiar') {
    if (['running', 'cancelling'].includes(status.job.state) || step === 3) return jobView();
    if (step === -1) {
      syncSelection();
      const panels = document.createElement('div'); panels.className = 'storage-panels';
      panels.append(storagePanel(0, source), storagePanel(1, destination)); content.append(panels);
      const start = button(status.demo ? 'Simular respaldo' : 'Iniciar respaldo', startBackup, 'primary');
      start.disabled = !source || !destination || source.id === destination.id ||
        (source.disk && source.disk === destination.disk) || busy || status.removing;
      content.append(start);
      if (busy || status.removal?.message) content.append(text('p', busy ? 'Retirando unidad…' : status.removal.message, 'hint'));
      return;
    }
    content.append(text('h1', ['1 · Elegir origen', '2 · Elegir destino', '3 · Confirmar respaldo'][step]));
    if (step < 2) {
      const list = (step === 0 ? devices.sources : devices.destinations).filter(d => d.available !== false && (step === 0 || d.id !== source?.id));
      const pages = Math.max(1, Math.ceil(list.length / 2)); page = Math.min(page, pages - 1);
      const e = document.createElement('div'); e.className = 'list';
      list.slice(page * 2, page * 2 + 2).forEach(d => e.append(button(d.label, () => { if (step === 0) source = d; else destination = d; step = -1; page = 0; })));
      content.append(e); if (!list.length) content.append(card('No hay dispositivos configurados.'));
      content.append(button('Volver', () => { step = -1; page = 0; }));
      if (pages > 1) pager(pages, p => { page = p; });
    } else {
      content.append(card(`De: ${source.label}`, `A: ${destination.label}`));
      content.append(text('p', status.demo ? 'Demo: no se copiarán archivos.' : 'Copiar sin borrar el origen.', 'hint'));
      actions(button('Volver', () => { step = 1; page = 0; }), button(status.demo ? 'Simular copia' : 'Iniciar copia', async () => {
        busy = true; try { status = await api('/api/backup', { source: source.id, destination: destination.id }); step = 3; } finally { busy = false; }
      }, 'primary'));
    }
  } else if (tab === 'Utilidades') {
    if (setting === 'Monitor') {
      const memory = monitor.memory || {};
      content.append(text('h1', 'Monitor del sistema'));
      const cpu = monitor.cpu_percent == null ? 'Midiendo…' : `${monitor.cpu_percent.toFixed(1)}%`;
      const systemCard = card(`CPU ${cpu}${monitor.temperature_c == null ? '' : ' · ' + monitor.temperature_c.toFixed(1) + ' °C'}`,
        `Memoria ${space(memory.used_bytes)} / ${space(memory.total_bytes)}`);
      systemCard.classList.add('transfer-metrics'); content.append(systemCard);
      const units = [...new Map([...devices.sources, ...devices.destinations].filter(d => d.disk).map(d => [d.disk, d])).values()];
      page = Math.min(page, Math.max(0, units.length - 1));
      const unit = units[page];
      if (unit) {const unitCard = card(`${unit.name || unit.label} · ${space(unit.capacity_bytes)}`, `Usado ${space(unit.used_bytes)} · Libre ${space(unit.free_bytes)}`); unitCard.classList.add('transfer-metrics'); content.append(unitCard);}
      actions(button('Volver', () => {setting = null; page = 0;}), button('Otra unidad', () => {page = (page + 1) % Math.max(1, units.length);}));
    } else {
      content.append(text('h1', 'Utilidades'));
      content.append(button('Archivos', async () => {tab = 'Archivos'; page = 0; await loadFiles();}));
      content.append(button('Monitor del sistema', async () => {setting = 'Monitor'; monitor = await api('/api/monitor');}));
    }
  } else if (tab === 'Archivos') {
    if (detail) {
      content.append(text('h1', detail.name), card(detail.directory ? 'Carpeta' : `Tamaño: ${(detail.size / 1000000).toFixed(1)} MB`, status.demo ? 'Archivo de demostración' : 'Consulta de solo lectura'));
      content.append(button('Volver a archivos', () => { detail = null; }, 'primary')); return;
    }
    content.append(text('h1', path || 'Archivos del respaldo'));
    const e = document.createElement('div'); e.className = 'list';
    files.entries.forEach(f => e.append(button(`${f.directory ? '▸ ' : ''}${f.name}`, async () => {
      if (f.directory) { path = path ? `${path}/${f.name}` : f.name; page = 0; await loadFiles(); } else detail = f;
    }))); content.append(e);
    if (!files.entries.length) content.append(card('Esta carpeta está vacía.'));
    pager(files.pages, async p => { page = p; await loadFiles(); }, path ? async () => { path = path.split('/').slice(0, -1).join('/'); page = 0; await loadFiles(); } : null);
  } else {
    content.append(text('h1', setting || 'Ajustes'));
    if (!setting) {
      const list = document.createElement('div'); list.className = 'list';
      list.classList.add('settings-list');
      ['Info', 'Copia', 'Wi-Fi', 'Bluetooth', 'Nube', 'Sistema'].forEach(s => list.append(button(s + ' ›', async () => { setting = s; page = 0; btDevice = null; if (s === 'Wi-Fi') wifi = await api('/api/wifi'); if (s === 'Info') info = await api('/api/info'); if (s === 'Bluetooth') bluetooth = await api('/api/bluetooth'); if (s === 'Nube') remote = await api('/api/remote'); }))); content.append(list);
    } else {
      if (setting === 'Bluetooth') {
        bluetoothView(); return;
      } else if (['Nube', 'Cuentas', 'Configurar nube'].includes(setting)) {
        remoteView(); return;
      } else if (setting === 'Info') {
        content.append(card(`Dispositivo: ${info.hostname || 'Consultando…'}`, `IP: ${info.ip || 'Sin dirección IP'}`, `MAC: ${info.mac || 'No disponible'}`, `Interfaz: ${info.interface || 'Sin conexión'}`));
      } else if (setting === 'Copia') {
        content.append(card('Verificación por checksum', 'Se aplica al próximo respaldo.'));
        content.append(button(status.checksum ? 'Checksum: activado' : 'Checksum: desactivado', async () => { status = await api('/api/settings', { checksum: !status.checksum }); }));
      } else if (setting === 'Wi-Fi') {
        if (!wifi.available) content.append(card(wifi.message || 'Consultando Wi-Fi…'));
        else {
          content.append(card(`${wifi.state} · ${wifi.connection}`, `Hotspot: ${wifi.hotspot}`));
          if (wifi.forced) content.append(text('p', `Contraseña: ${wifi.password || ''} · IP: ${wifi.address || ''}`, 'hint'));
          const hotspot = button('Hotspot', async () => {
            if (!confirm('Activar hotspot y desconectar el Wi-Fi actual. Tus redes y contraseñas quedan guardadas.')) return;
            await api('/api/wifi', {action: 'hotspot'}); wifi = await api('/api/wifi');
          });
          hotspot.disabled = !!wifi.forced;
          actions(button(wifi.forced ? 'Volver a Wi-Fi' : 'Conectar red', async () => {
            if (wifi.forced) {
              await api('/api/wifi', {action: 'resume'}); wifi = await api('/api/wifi'); return;
            }
            const credentials = await wifiCredentials();
            if (!credentials) return;
            await api('/api/wifi', {action: 'connect', ...credentials}); wifi = await api('/api/wifi');
          }), hotspot);
        }
      } else if (setting === 'Dispositivos') {
        const list = [...new Map([...devices.sources, ...devices.destinations]
          .filter(d => d.disk && d.id.startsWith('auto:')).map(d => [d.disk, d])).values()];
        const active = ['running', 'cancelling'].includes(status.job.state);
        content.append(text('p', active ? 'Esperá a que termine el respaldo.' : status.removal?.message || 'Elegí el dispositivo que querés retirar.', 'hint'));
        page = Math.min(page, Math.max(0, Math.ceil(list.length / 2) - 1));
        list.slice(page * 2, page * 2 + 2).forEach(d => {
          const b = button(d.label, async () => {
            if (!confirm(`¿Retirar ${d.label}? Se desmontarán todas las particiones de ese disco. Esperá la confirmación antes de desconectarlo.`)) return;
            busy = true;
            try { status = await api('/api/remove', {device: d.id}); devices = await api('/api/devices'); }
            finally { busy = false; }
          });
          b.disabled = active || busy || status.removing || status.demo;
          content.append(b);
        });
        if (!list.length) content.append(text('p', 'No hay discos extraíbles conectados.'));
        if (list.length > 2) pager(Math.ceil(list.length / 2), p => { page = p; });
      } else {
        content.append(button('Retirar dispositivos', () => { setting = 'Dispositivos'; page = 0; }));
        const poweroff = button('Apagar', async () => {
          if (confirm('¿Apagar la Raspberry Pi? Esperá antes de quitar la alimentación.')) status = await api('/api/shutdown', {});
        });
        poweroff.disabled = status.demo || busy || status.removing || ['running', 'cancelling'].includes(status.job.state);
        content.append(poweroff);
      }
      content.append(button('Volver a ajustes', () => { setting = null; }, 'primary'));
    }
  }
}
async function refresh() {
  if (status.shutting_down) return;
  try {
    if (tab === 'Utilidades' && setting === 'Monitor') {monitor = await api('/api/monitor'); render();}
    if (++wifiTicks % 5 === 0) {
      info = await api('/api/info');
      updateWifiIndicator();
      if (setting === 'Info') render();
    }
    if (wifiTicks === 1 || wifiTicks % (setting === 'Bluetooth' ? 2 : 5) === 0) {
      const current = await api('/api/bluetooth');
      const changed = JSON.stringify(current) !== JSON.stringify(bluetooth);
      bluetooth = current; updateBluetoothIndicator();
      if (changed && setting === 'Bluetooth') render();
    }
    if (setting === 'Wi-Fi' && wifiTicks % 5 === 0) {
      const current = await api('/api/wifi');
      if (JSON.stringify(current) !== JSON.stringify(wifi)) { wifi = current; render(); }
    }
    const [next, found] = await Promise.all([api('/api/status'), api('/api/devices')]);
    if (step === 2 && [source, destination].some((d, i) => d?.id.startsWith('auto:') && !found[i ? 'destinations' : 'sources'].some(x => x.id === d.id))) step = -1;
    if (JSON.stringify(next) !== JSON.stringify(status) || JSON.stringify(found) !== JSON.stringify(devices) || error === 'Sin conexión con el servidor') {
      const focused = document.activeElement?.textContent;
      status = next; devices = found; if (error === 'Sin conexión con el servidor') error = ''; render();
      [...document.querySelectorAll('button')].find(b => b.textContent === focused)?.focus();
    }
  } catch { error = 'Sin conexión con el servidor'; render(); }
}
(async () => { try { [status, devices, info] = await Promise.all([api('/api/status'), api('/api/devices'), api('/api/info')]); } catch { error = 'Sin conexión con el servidor'; } render(); setInterval(refresh, 1000); })();
