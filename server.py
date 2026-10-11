"""Touch UI gateway. Demo by default; explicit configuration enables upstream CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from hardware import discover, Wifi, network_info, remove_device, SystemMonitor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from telemetry import BackupTelemetry
from process_control import stop_group

ROOT = Path(__file__).resolve().parent
SOURCE_TYPES = {'camera', 'anyusb', 'usb', 'internal', 'nvme'}
TARGET_TYPES = {'usb', 'internal', 'nvme'}


def backup_result(code, diagnostic):
    import re
    normalized = ' '.join(diagnostic.lower().split())
    if 'invalid mode combination' in normalized:
        return {'state': 'error', 'progress': None, 'message': 'No se copió: combinación de origen y destino inválida'}
    if code != 0:
        return {'state': 'error', 'progress': None, 'message': 'Falló el respaldo · podés reintentar'}
    summaries = list(re.finditer(r'backup complete\.\s*(\d+) of (\d+) files copied', diagnostic, re.I))
    if summaries:
        summary = summaries[-1]
        copied, expected = map(int, summary.groups())
        if copied >= expected:
            return {'state': 'success', 'progress': 100, 'message': 'Copia completada con éxito'}
        return {'state': 'error', 'progress': None, 'message': 'Respaldo incompleto · podés reintentar'}
    return {'state': 'review', 'progress': None, 'message': 'No se pudo confirmar el resultado · revisar registro'}


def command(config, source, target, checksum):
    if source['engine'] not in SOURCE_TYPES or target['engine'] not in TARGET_TYPES:
        raise ValueError('Tipo de almacenamiento no admitido')
    if source['id'] == target['id'] or (source.get('preset') and source.get('preset') == target.get('preset')):
        raise ValueError('Origen y destino deben ser distintos')
    source_engine = 'usb' if source['engine'] == 'anyusb' and source.get('preset') else source['engine']
    if source_engine == target['engine'] and not (source.get('preset') and target.get('preset')):
        raise ValueError('Se requieren identificadores para distinguir los dispositivos')
    return [config.get('python', 'python3'), str(Path(config['engine_dir']) / 'backup.py'),
            '--SourceName', source_engine, '--TargetName', target['engine'],
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
        self.target_disk = None
        self.cancel_requested = threading.Event()
        self.removing = False
        self.removal = {}
        self.cleanup_failed = False
        self.monitor = SystemMonitor()
        self.shutting_down = False

    def devices(self):
        # Serializes read-only capacity probes against starting a job or removal.
        with self.lock:
            return self._devices()

    def _devices(self):
        if self.config:
            profiles = {k: [dict(d) for d in self.config.get(k, [])] for k in ('sources', 'destinations')}
            try:
                found = discover(probe=self.job['state'] not in ('running', 'cancelling') and not self.removing and not self.shutting_down)
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
                        d['available'] = not d.get('preset') or d.get('preset') in physical
                        if d.get('preset') in physical:
                            d['disk'] = physical[d['preset']]
                    presets = {d.get('preset') for d in found[group]}
                    profiles[group] = found[group] + [d for d in profiles[group] if d.get('preset') not in presets]
                return dict(profiles, automatic=found['automatic'])
            except (OSError, ValueError, subprocess.SubprocessError):
                return dict(profiles, automatic={}, detection_error='Detección no disponible; seleccioná manualmente')
        return {'sources': [{'id': 'card', 'label': 'Tarjeta SD · ejemplo'}, {'id': 'camera', 'label': 'Cámara USB · ejemplo'}, {'id': 'usb', 'label': 'Memoria USB · ejemplo'}],
                'destinations': [{'id': 'ssd', 'label': 'SSD principal · ejemplo'}, {'id': 'disk', 'label': 'Disco USB · ejemplo'}],
                'automatic': {'source': 'card', 'destination': 'ssd'}}

    def status(self):
        with self.lock:
            return {'demo': self.config is None, 'job': dict(self.job), 'checksum': self.checksum,
                    'removing': self.removing, 'removal': dict(self.removal), 'shutting_down': self.shutting_down}

    def shutdown(self):
        with self.lock:
            if not self.config:
                raise ValueError('Apagar no está disponible en demo')
            if self.job['state'] in ('running', 'cancelling') or self.cleanup_failed or self.removing:
                raise ValueError('Esperá a que termine el respaldo o la retirada antes de apagar')
            if self.shutting_down:
                raise ValueError('El equipo ya se está apagando')
            self.shutting_down = True
        try:
            # systemd stops services and flushes/unmounts filesystems before poweroff.
            subprocess.run(['systemctl', 'poweroff', '--no-block'], check=True,
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            with self.lock:
                self.shutting_down = False
            raise ValueError('No se pudo apagar el equipo') from exc

    def cancel(self):
        with self.lock:
            if self.job['state'] != 'running':
                raise ValueError('No hay un respaldo en curso para cancelar')
            self.cancel_requested.set()
            self.job.update(state='cancelling', message='Cancelando · esperá antes de retirar dispositivos')

    def remove(self, identifier):
        with self.lock:
            if self.shutting_down:
                raise ValueError('El equipo se está apagando')
            if self.job['state'] in ('running', 'cancelling') or self.cleanup_failed:
                raise ValueError('Primero esperá a que termine o se cancele el respaldo')
            if self.removing:
                raise ValueError('Ya se está retirando un dispositivo')
            if not self.config:
                raise ValueError('La retirada segura no está disponible en demo')
            self.removing = True
            self.removal = {}
        try:
            result = remove_device(identifier)
            with self.lock:
                self.removal = result
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('No se pudo confirmar la retirada segura. No desconectes el dispositivo todavía') from exc
        finally:
            with self.lock:
                self.removing = False

    def start(self, data):
        devices = self.devices()
        if any(data.get(key) not in [d['id'] for d in devices[group]]
               for key, group in [('source', 'sources'), ('destination', 'destinations')]):
            raise ValueError('Selección no válida')
        with self.lock:
            if self.shutting_down:
                raise ValueError('El equipo se está apagando')
            if self.job['state'] in ('running', 'cancelling') or self.cleanup_failed:
                raise ValueError('Ya hay un respaldo en curso')
            if self.removing:
                raise ValueError('Esperá a que se retire el dispositivo')
            self.cancel_requested.clear()
            self.removal = {}
            argv = None
            if self.config:
                source = next(d for d in devices['sources'] if d['id'] == data['source'])
                target = next(d for d in devices['destinations'] if d['id'] == data['destination'])
                if source.get('available') is False or target.get('available') is False:
                    raise ValueError('Conectá el origen y el destino antes de iniciar')
                if source.get('disk') and source.get('disk') == target.get('disk'):
                    raise ValueError('Origen y destino pertenecen al mismo disco')
                argv = command(self.config, source, target, self.checksum)
                self.target_disk = target.get('disk')
                if not (Path(self.config['engine_dir']) / 'backup.py').is_file():
                    raise ValueError('No se encontró backup.py en la instalación configurada')
            self.job = {'state': 'running', 'progress': 0 if not argv else None,
                        'message': 'Simulación en curso' if not argv else 'Preparando respaldo'}
        threading.Thread(target=self.run, args=(argv,), daemon=True).start()

    def run(self, argv):
        try:
            if argv is None:
                for progress in range(10, 101, 10):
                    if self.cancel_requested.is_set():
                        break
                    time.sleep(.4)
                    with self.lock:
                        self.job['progress'] = progress
                result = {'state': 'success', 'progress': 100, 'message': 'Simulación completa · no se copiaron archivos'}
            else:
                runtime = Path(os.environ.get('LBB_SCREEN_STATE_DIR', ROOT / '.runtime'))
                runtime.mkdir(exist_ok=True)
                upstream_log = Path(self.config['engine_dir']) / 'tmp/little-backup-box.log'
                offset = upstream_log.stat().st_size if upstream_log.exists() else 0
                with (runtime / 'engine.log').open('w', encoding='utf-8') as log:
                    log.write('Ejecutando respaldo\n' + json.dumps(argv, ensure_ascii=False) + '\n')
                    log.flush()
                    if self.cancel_requested.is_set():
                        raise InterruptedError('Cancelado antes de iniciar el motor')
                    process = subprocess.Popen(argv, cwd=self.config['engine_dir'], stdout=log,
                                               stderr=log, shell=False, start_new_session=True)
                    tracker = BackupTelemetry(self.config['engine_dir'], self.target_disk, offset)
                    stop = threading.Event()
                    def monitor():
                        while not stop.wait(2):
                            try:
                                update = tracker.sample()
                                with self.lock:
                                    if self.job['state'] == 'running':
                                        self.job.update(update)
                            except (OSError, ValueError):
                                pass
                    watcher = threading.Thread(target=monitor, daemon=True)
                    watcher.start()
                    cancel_stopped = False
                    try:
                        while True:
                            if self.cancel_requested.is_set():
                                try:
                                    stop_group(process)
                                    cancel_stopped = True
                                except (OSError, ValueError):
                                    self.cleanup_failed = True
                                    raise
                                code = process.wait()
                                break
                            try:
                                code = process.wait(timeout=.5)
                                break
                            except subprocess.TimeoutExpired:
                                continue
                        if self.cancel_requested.is_set() and not cancel_stopped and not self.cleanup_failed:
                            try:
                                stop_group(process)
                            except (OSError, ValueError):
                                self.cleanup_failed = True
                                raise
                    finally:
                        stop.set()
                        watcher.join(timeout=3)
                    diagnostic = ''
                    try:
                        with upstream_log.open('rb') as upstream:
                            size = upstream.seek(0, 2)
                            upstream.seek(max(offset if size >= offset else 0, size - 65536))
                            diagnostic = upstream.read().decode('utf-8', errors='replace')
                        log.write('\nRegistro interno del motor:\n' + diagnostic)
                    except OSError:
                        pass
                # Upstream can exit 0 despite backup errors; never equate this with verified success.
                result = backup_result(code, diagnostic)
        except Exception:
            result = {'state': 'error', 'progress': None, 'message': 'No se pudo ejecutar el motor · revisar configuración'}
        with self.lock:
            if self.cancel_requested.is_set():
                result = {'state': 'cancelling' if self.cleanup_failed else 'cancelled', 'progress': None,
                          'message': 'No se confirmó la detención. No retires los dispositivos.' if self.cleanup_failed else
                          'Respaldo cancelado · pueden quedar archivos incompletos'}
            if self.job.get('metrics'):
                result['metrics'] = dict(self.job['metrics'])
                if result['state'] not in ('running', 'cancelling'):
                    result['metrics']['eta'] = None
                if result['state'] == 'success':
                    result['metrics'].pop('files_processed', None)
                    result['metrics'].pop('files_total', None)
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
            if url.path == '/api/info':
                return self.reply(network_info())
            if url.path == '/api/monitor':
                return self.reply(self.server.engine.monitor.sample())
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
            elif self.path == '/api/cancel':
                self.server.engine.cancel()
            elif self.path == '/api/shutdown':
                self.server.engine.shutdown()
            elif self.path == '/api/remove':
                if not isinstance(data.get('device'), str):
                    raise ValueError('Indicá el dispositivo que querés retirar')
                self.server.engine.remove(data['device'])
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
