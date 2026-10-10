"""Touch UI gateway. Demo by default; explicit configuration enables upstream CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from hardware import discover, Wifi
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
SOURCE_TYPES = {'camera', 'anyusb', 'usb', 'internal', 'nvme'}
TARGET_TYPES = {'usb', 'internal', 'nvme'}


def command(config, source, target, checksum):
    if source['engine'] not in SOURCE_TYPES or target['engine'] not in TARGET_TYPES:
        raise ValueError('Tipo de almacenamiento no admitido')
    if source['id'] == target['id'] or (source.get('preset') and source.get('preset') == target.get('preset')):
        raise ValueError('Origen y destino deben ser distintos')
    if source['engine'] == target['engine'] and not (source.get('preset') and target.get('preset')):
        raise ValueError('Se requieren identificadores para distinguir los dispositivos')
    return [config.get('python', 'python3'), str(Path(config['engine_dir']) / 'backup.py'),
            '--SourceName', source['engine'], '--TargetName', target['engine'],
            '--device-identifier-preset-source', source.get('preset', ''),
            '--device-identifier-preset-target', target.get('preset', ''),
            '--move-files', 'False', '--move-files2', 'False', '--rename-files', 'False',
            '--update-exif', 'False', '--generate-thumbnails', 'False',
            '--power-off', 'False', '--checksum', str(checksum)]


class Engine:
    def __init__(self, config=None):
        self.config = config
        self.lock = threading.Lock()
        self.job = {'state': 'idle', 'progress': None, 'message': 'Listo para respaldar'}
        self.checksum = True
        self.wifi = Wifi()

    def devices(self):
        if self.config:
            profiles = {k: [dict(d) for d in self.config[k]] for k in ('sources', 'destinations')}
            try:
                found = discover()
                configured_cards = {d.get('preset') for d in profiles['sources'] if d.get('engine') == 'anyusb' and d.get('preset')}
                for d in found['sources']:
                    if d.get('preset') in configured_cards:
                        d['sd'], d['engine'] = True, 'anyusb'
                for d in found['destinations']:
                    if d.get('preset') in configured_cards:
                        d['sd'] = True
                cards = [d for d in found['sources'] if d.get('sd')]
                disks = [d for d in found['destinations'] if not d.get('sd')]
                found['automatic'] = {'source': cards[0]['id'] if len(cards) == 1 else None,
                                      'destination': disks[0]['id'] if len(disks) == 1 else None}
                physical = {d['preset']: d['disk'] for d in found['sources']}
                for group in profiles:
                    for d in profiles[group]:
                        if d.get('preset') in physical:
                            d['disk'] = physical[d['preset']]
                    presets = {d.get('preset') for d in found[group]}
                    profiles[group] = found[group] + [d for d in profiles[group] if d.get('preset') not in presets]
                return dict(profiles, automatic=found['automatic'])
            except (OSError, ValueError, subprocess.SubprocessError):
                return dict(profiles, automatic={}, detection_error='Detección no disponible; seleccioná manualmente')
        return {'sources': [{'id': 'card', 'label': 'Tarjeta SD · ejemplo'}, {'id': 'camera', 'label': 'Cámara USB · ejemplo'}, {'id': 'usb', 'label': 'Memoria USB · ejemplo'}],
                'destinations': [{'id': 'ssd', 'label': 'SSD principal · ejemplo'}, {'id': 'disk', 'label': 'Disco USB · ejemplo'}]}

    def status(self):
        with self.lock:
            return {'demo': self.config is None, 'job': dict(self.job), 'checksum': self.checksum}

    def start(self, data):
        devices = self.devices()
        if any(data.get(key) not in [d['id'] for d in devices[group]]
               for key, group in [('source', 'sources'), ('destination', 'destinations')]):
            raise ValueError('Selección no válida')
        with self.lock:
            if self.job['state'] == 'running':
                raise ValueError('Ya hay un respaldo en curso')
            argv = None
            if self.config:
                source = next(d for d in devices['sources'] if d['id'] == data['source'])
                target = next(d for d in devices['destinations'] if d['id'] == data['destination'])
                if source.get('disk') and source.get('disk') == target.get('disk'):
                    raise ValueError('Origen y destino pertenecen al mismo disco')
                argv = command(self.config, source, target, self.checksum)
                if not (Path(self.config['engine_dir']) / 'backup.py').is_file():
                    raise ValueError('No se encontró backup.py en la instalación configurada')
            self.job = {'state': 'running', 'progress': 0 if not argv else None,
                        'message': 'Simulación en curso' if not argv else 'Motor en ejecución · sin porcentaje disponible'}
        threading.Thread(target=self.run, args=(argv,), daemon=True).start()

    def run(self, argv):
        try:
            if argv is None:
                for progress in range(10, 101, 10):
                    time.sleep(.4)
                    with self.lock:
                        self.job['progress'] = progress
                result = {'state': 'success', 'progress': 100, 'message': 'Simulación completa · no se copiaron archivos'}
            else:
                runtime = Path(os.environ.get('LBB_SCREEN_STATE_DIR', ROOT / '.runtime'))
                runtime.mkdir(exist_ok=True)
                with (runtime / 'engine.log').open('w', encoding='utf-8') as log:
                    process = subprocess.Popen(argv, cwd=self.config['engine_dir'], stdout=log, stderr=log, shell=False)
                    code = process.wait()
                # Upstream can exit 0 despite backup errors; never equate this with verified success.
                result = {'state': 'review' if code == 0 else 'error', 'progress': None,
                          'message': 'Motor finalizado · revisar registro del respaldo' if code == 0 else f'El motor terminó con error ({code})'}
        except Exception:
            result = {'state': 'error', 'progress': None, 'message': 'No se pudo ejecutar el motor · revisar configuración'}
        with self.lock:
            self.job = result

    def files(self, relative, page):
        if not self.config:
            entries = [{'name': f'Sesión {i:02}', 'directory': False, 'size': 120000000} for i in range(1, 8)]
        else:
            root = Path(self.config['files_root']).resolve()
            current = (root / relative).resolve()
            if not current.is_relative_to(root):
                raise ValueError('Ruta no permitida')
            entries = []
            for p in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
                if p.is_symlink():
                    continue
                entries.append({'name': p.name, 'directory': p.is_dir(), 'size': p.stat().st_size if p.is_file() else None})
        pages = max(1, (len(entries) + 1) // 2)
        page = min(max(0, page), pages - 1)
        return {'entries': entries[page * 2:page * 2 + 2], 'page': page, 'pages': pages}


class Handler(BaseHTTPRequestHandler):
    def reply(self, value, code=200):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path == '/api/status':
                return self.reply(self.server.engine.status())
            if url.path == '/api/devices':
                return self.reply(self.server.engine.devices())
            if url.path == '/api/wifi':
                return self.reply(self.server.engine.wifi.status() if self.server.engine.config else
                                  {'available': False, 'message': 'Wi-Fi no se modifica en modo demo'})
            if url.path == '/api/files':
                query = parse_qs(url.query)
                return self.reply(self.server.engine.files(query.get('path', [''])[0], int(query.get('page', ['0'])[0])))
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}.get(url.path)
            if not name:
                return self.reply({'error': 'No encontrado'}, 404)
            payload = (ROOT / 'web' / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name])
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError, OSError) as exc:
            self.reply({'error': 'No se pudo leer la carpeta' if isinstance(exc, OSError) else str(exc)}, 400)

    def do_POST(self):
        # Require same-origin JSON: cross-origin forms and fetches cannot start jobs.
        origin = self.headers.get('Origin')
        if (origin and origin != 'http://' + self.headers.get('Host', '')) or self.headers.get('Content-Type') != 'application/json':
            return self.reply({'error': 'Solicitud no permitida'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 4096:
                raise ValueError('Solicitud no válida')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Solicitud no válida')
            if self.path == '/api/backup':
                self.server.engine.start(data)
            elif self.path == '/api/wifi':
                if not self.server.engine.config:
                    raise ValueError('Wi-Fi no se modifica en modo demo')
                self.server.engine.wifi.apply(data)
            elif self.path == '/api/settings':
                if not isinstance(data.get('checksum'), bool):
                    raise ValueError('Ajuste no válido')
                with self.server.engine.lock:
                    self.server.engine.checksum = data['checksum']
            else:
                return self.reply({'error': 'No encontrado'}, 404)
            self.reply(self.server.engine.status())
        except (ValueError, KeyError) as exc:
            self.reply({'error': str(exc)}, 400)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8')) if args.config else None
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.engine = Engine(config)
    print(f'http://127.0.0.1:{args.port} · {"REAL" if config else "DEMO"}', flush=True)
    server.serve_forever()
