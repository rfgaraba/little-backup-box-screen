// Local UI preview for machines without Python. No hardware or network changes.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..', 'web');
let card = true, disk = true, checksum = true;
let job = {state:'idle', progress:null, message:'Listo para simular'};
let wifi = {available:true, state:'HOTSPOT', connection:'', hotspot:'little-backup-box-demo', mode:'single',
  forced:false,
  networks:[{ssid:'Wi-Fi del hotel',security:'encrypted'},{ssid:'Mi teléfono',security:'encrypted'}]};
const status = () => ({demo:true, checksum, job});
const panel = `<aside style="position:fixed;bottom:12px;left:50%;transform:translateX(-50%);width:min(470px,96vw);font:14px system-ui;color:#eff5fb;text-align:center;background:#1b2d3e;padding:8px;border-radius:8px">
Demo visual · sin copias ni cambios de Wi-Fi<br>
<label><input id="sd-preview" type="checkbox" checked> SD conectada</label>
<label><input id="disk-preview" type="checkbox" checked> Disco conectado</label>
<script>for(const id of ['sd-preview','disk-preview'])document.getElementById(id).onchange=()=>fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({card:document.getElementById('sd-preview').checked,disk:document.getElementById('disk-preview').checked})});</script></aside>`;
const server = http.createServer(async (req, res) => {
  function json(value, code=200) {res.writeHead(code, {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));}
  try {
    const url = new URL(req.url, 'http://127.0.0.1');
    if(req.method === 'POST') {
      if(req.headers.origin && req.headers.origin !== 'http://' + req.headers.host) return json({error:'Solicitud no permitida'},403);
      let raw = ''; for await(const chunk of req) {raw += chunk; if(raw.length > 4096) return json({error:'Solicitud demasiado grande'},400);}
      const data = JSON.parse(raw);
      if(url.pathname === '/api/preview') {card = !!data.card; disk = !!data.disk;}
      else if(url.pathname === '/api/settings') checksum = !!data.checksum;
      else if(url.pathname === '/api/backup') {
        if(job.state === 'running') return json({error:'Ya hay una simulación en curso'},400);
        if(!card || !disk || data.source !== 'card' || data.destination !== 'ssd') return json({error:'Conectá la SD y el disco simulados'},400);
        job = {state:'running',progress:0,message:'Simulación en curso'};
        const timer = setInterval(() => {
          job.progress += 10;
          if(job.progress >= 100) {clearInterval(timer);job = {state:'success',progress:100,message:'Simulación completa · no se copiaron archivos'};}
        },400);
      } else if(url.pathname === '/api/wifi') {
        wifi = {...wifi, forced:data.action === 'hotspot', password:data.action === 'hotspot' ? 'demo12345678' : '',
          address:data.action === 'hotspot' ? '10.42.0.1/24' : '',
          state:data.action === 'connect' || data.action === 'resume' ? 'CONNECTED' : 'HOTSPOT',
          connection:data.action === 'connect' ? String(data.ssid || '') : data.action === 'resume' ? 'Wi-Fi del hotel' : ''};
      } else return json({error:'No encontrado'},404);
      return json(status());
    }
    if(url.pathname === '/api/status') return json(status());
    if(url.pathname === '/api/wifi') return json(wifi);
    if(url.pathname === '/api/devices') return json({sources:card ? [{id:'card',label:'Tarjeta SD · ejemplo'}] : [],
      destinations:disk ? [{id:'ssd',label:'SSD principal · ejemplo'}] : [], automatic:{source:card ? 'card' : null,destination:disk ? 'ssd' : null}});
    if(url.pathname === '/api/files') {
      const page = Math.min(3, Math.max(0, Number(url.searchParams.get('page')) || 0));
      return json({entries:Array.from({length:7},(_,i)=>({name:`Sesión ${String(i+1).padStart(2,'0')}`,directory:false,size:120000000})).slice(page*2,page*2+2),page,pages:4});
    }
    const file = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.pathname];
    if(!file) return json({error:'No encontrado'},404);
    let body = fs.readFileSync(path.join(root,file),'utf8');
    if(file === 'index.html') body = body.replace('</body>', panel + '</body>');
    res.writeHead(200,{'Content-Type':file.endsWith('.html') ? 'text/html; charset=utf-8' : file.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8','Cache-Control':'no-store'});
    res.end(body);
  } catch {json({error:'Error en la demo'},400);}
});
server.listen(8080,'127.0.0.1',()=>console.log('Demo visual: http://127.0.0.1:8080'));
server.on('error',e=>{console.error(e.message);process.exitCode=1;});
