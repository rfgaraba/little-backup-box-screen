const content = document.querySelector('#content');
const nav = document.querySelector('nav');
let tab = 'Copiar', step = -1, source = null, destination = null, page = 0;
let wifi = {};
let wifiTicks = 0;
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
  const job = status.job, running = job.state === 'running';
  content.append(text('h1', running ? 'Respaldo en curso' : job.state === 'idle' ? 'Listo para respaldar' : 'Resultado del respaldo'));
  const c = card(job.message);
  if (job.progress !== null) { c.prepend(text('div', `${job.progress}%`, 'metric')); }
  if (running) { const p = document.createElement('progress'); p.max = 100; if (job.progress !== null) p.value = job.progress; p.setAttribute('aria-label', 'Progreso del respaldo'); c.append(p); }
  content.append(c);
  if (job.state === 'idle') content.append(text('p', status.demo ? 'Probá el flujo sin copiar archivos.' : 'Seleccioná origen y destino configurados.'));
  content.append(button(running ? 'Ver progreso' : 'Nuevo respaldo', () => { tab = 'Copiar'; if (!running) { step = -1; page = 0; source = destination = null; } }, 'primary'));
}
function render() {
  document.querySelector('#mode').textContent = status.demo ? 'DEMO' : 'MOTOR REAL';
  nav.replaceChildren(...['Estado', 'Copiar', 'Archivos', 'Ajustes'].map(name => {
    const b = button(name, async () => { tab = name; detail = setting = null; page = 0; if (name === 'Archivos') await loadFiles(); });
    if (name === tab) b.setAttribute('aria-current', 'page'); return b;
  }));
  content.replaceChildren();
  if (error) { content.append(text('h1', 'No se pudo continuar'), card(error)); content.append(button('Volver', () => { error = ''; }, 'primary')); return; }
  if (tab === 'Estado') return jobView();
  if (tab === 'Copiar') {
    if (status.job.state === 'running' || step === 3) return jobView();
    if (step === -1) {
      source = devices.sources.find(d => d.id === devices.automatic?.source);
      destination = devices.destinations.find(d => d.id === devices.automatic?.destination);
      content.append(text('h1', 'Backup'), card(`Origen: ${source?.label || 'conectá una SD'}`, `Destino: ${destination?.label || 'conectá un disco USB'}`));
      const start = button(status.demo ? 'Simular backup' : 'Backup', async () => {
        busy = true; try { status = await api('/api/backup', {source: source.id, destination: destination.id}); step = 3; } finally { busy = false; }
      }, 'primary');
      start.disabled = !source || !destination || busy;
      content.append(text('p', devices.detection_error || 'Si no se detectan, seleccioná origen y destino.', 'hint'));
      actions(button('Seleccionar manual', () => { step = 0; page = 0; }), start);
      return;
    }
    content.append(text('h1', ['1 · Elegir origen', '2 · Elegir destino', '3 · Confirmar respaldo'][step]));
    if (step < 2) {
      const list = (step === 0 ? devices.sources : devices.destinations).filter(d => step === 0 || d.id !== source?.id);
      const pages = Math.max(1, Math.ceil(list.length / 2)); page = Math.min(page, pages - 1);
      const e = document.createElement('div'); e.className = 'list';
      list.slice(page * 2, page * 2 + 2).forEach(d => e.append(button(d.label, () => { if (step === 0) source = d; else destination = d; step++; page = 0; })));
      content.append(e); if (!list.length) content.append(card('No hay dispositivos configurados.'));
      if (step === 1) content.append(button('Volver al origen', () => { step = 0; page = 0; }));
      if (pages > 1) pager(pages, p => { page = p; });
    } else {
      content.append(card(`De: ${source.label}`, `A: ${destination.label}`));
      content.append(text('p', status.demo ? 'Demo: no se copiarán archivos.' : 'Copiar sin borrar el origen.', 'hint'));
      actions(button('Volver', () => { step = 1; page = 0; }), button(status.demo ? 'Simular copia' : 'Iniciar copia', async () => {
        busy = true; try { status = await api('/api/backup', { source: source.id, destination: destination.id }); step = 3; } finally { busy = false; }
      }, 'primary'));
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
      ['Copia', 'Wi-Fi', 'Sistema'].forEach(s => list.append(button(s + ' ›', async () => { setting = s; if (s === 'Wi-Fi') wifi = await api('/api/wifi'); }))); content.append(list);
    } else {
      if (setting === 'Copia') {
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
      } else content.append(card(status.demo ? 'Modo demo · sin motor conectado' : 'Adaptador CLI de Little Backup Box', 'Ajustes de copia: solo esta sesión'));
      content.append(button('Volver a ajustes', () => { setting = null; }, 'primary'));
    }
  }
}
async function refresh() {
  try {
    if (setting === 'Wi-Fi' && ++wifiTicks % 5 === 0) {
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
(async () => { try { [status, devices] = await Promise.all([api('/api/status'), api('/api/devices')]); } catch { error = 'Sin conexión con el servidor'; } render(); setInterval(refresh, 1000); })();
