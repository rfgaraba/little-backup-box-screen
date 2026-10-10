"""Install the touch frontend and missing OS dependencies on Linux/systemd."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen

SOURCE = Path(__file__).resolve().parent
APP = Path('/opt/little-backup-box-screen')
ETC = Path('/etc/little-backup-box-screen')
UNIT = Path('/etc/systemd/system/little-backup-box-screen.service')
SERVICE = UNIT.name
FILES = ('server.py', 'hardware.py', 'native.py', 'native_install.py', 'tools/display_probe.py', 'tools/display_console.py', 'web/index.html', 'web/app.js', 'web/style.css', 'LICENSE', 'README.md', 'config.example.json')


def validate_config(config, check_paths=True):
    if not isinstance(config, dict):
        raise ValueError('La configuración debe ser un objeto JSON')
    for key in ('engine_dir', 'files_root', 'python'):
        if not isinstance(config.get(key), str) or not config[key].startswith('/'):
            raise ValueError(f'{key} debe ser una ruta absoluta de Linux')
    identifiers = set()
    for group, allowed in [('sources', {'camera', 'anyusb', 'usb', 'internal', 'nvme'}),
                           ('destinations', {'usb', 'internal', 'nvme'})]:
        devices = config.get(group, [])
        if not isinstance(devices, list):
            raise ValueError(f'{group} debe ser una lista; puede estar vacía para detección automática')
        for device in devices:
            if not isinstance(device, dict) or device.get('engine') not in allowed:
                raise ValueError(f'Tipo de dispositivo inválido en {group}')
            for key in ('id', 'label'):
                if not isinstance(device.get(key), str) or not device[key].strip():
                    raise ValueError(f'Falta {key} en {group}')
            if device['id'] in identifiers:
                raise ValueError('Los id de dispositivos deben ser únicos')
            identifiers.add(device['id'])
            preset = device.get('preset', '')
            if not isinstance(preset, str) or 'REEMPLAZAR' in preset:
                raise ValueError('Reemplazá los UUID de ejemplo por los dispositivos reales')
    if check_paths:
        if not (Path(config['engine_dir']) / 'backup.py').is_file():
            raise ValueError('engine_dir no contiene backup.py; instalá primero Little Backup Box')
        if not Path(config['files_root']).is_dir():
            raise ValueError('files_root debe ser una carpeta existente')
        if not os.access(config['python'], os.X_OK):
            raise ValueError('El intérprete del motor no existe o no es ejecutable')


def validate_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('El puerto debe ser un entero entre 1 y 65535')
    return port


def selected_port(port, previous):
    return validate_port(port if port is not None else previous.get('port', 8080))


def check_port_available(port):
    import socket
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise ValueError(f'El puerto {port} está ocupado o no está disponible; elegí otro con --port') from exc


def service_text(mode, port=8080):
    validate_port(port)
    extra = ' --config /etc/little-backup-box-screen/config.json' if mode == 'real' else ''
    identity = 'User=root\n' if mode == 'real' else 'DynamicUser=yes\nProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nNoNewPrivileges=yes\n'
    return f'''[Unit]
Description=Little Backup Box - pantalla tactil
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/little-backup-box-screen
ExecStart=/usr/bin/python3 /opt/little-backup-box-screen/server.py --port {port}{extra}
Environment=PYTHONUNBUFFERED=1
Environment=LBB_SCREEN_STATE_DIR=/var/lib/little-backup-box-screen
StateDirectory=little-backup-box-screen
StateDirectoryMode=0700
UMask=0077
{identity}Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
'''


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def automatic_config(engine_dir=None):
    if engine_dir is not None:
        candidates = [Path(engine_dir)]
    else:
        candidates = [Path('/var/www/html/little-backup-box'), Path('/opt/little-backup-box')]
        candidates += list(Path('/home').glob('*/little-backup-box'))
        candidates += [Path('/root/little-backup-box'), SOURCE.parent / 'little-backup-box']
    found = sorted({p.resolve() for p in candidates if (p / 'backup.py').is_file()})
    if len(found) != 1:
        raise ValueError('No se encontró un único motor Little Backup Box. Instalalo primero o indicá --engine-dir /ruta/que/contiene/backup.py. Para probar la pantalla sin motor, usá --mode demo')
    return {'engine_dir': str(found[0]), 'python': '/usr/bin/python3',
            'files_root': '/media', 'sources': [], 'destinations': []}


def automatic_framebuffer():
    devices = sorted(str(p) for p in Path('/dev').glob('fb[0-9]*') if p.is_char_device())
    if len(devices) == 1:
        return devices[0]
    raise ValueError('No se pudo identificar una única pantalla framebuffer. Indicá --framebuffer /dev/fbN; comprobá el controlador si no hay ninguna')


def plan(mode=None, config_path=None, replace=False, check_paths=True, engine_dir=None):
    previous = read_json(ETC / 'install.json') if (ETC / 'install.json').exists() else {}
    mode = mode or ('real' if config_path or engine_dir else previous.get('mode', 'real'))
    if mode not in ('demo', 'real'):
        raise ValueError('Modo inválido en los datos de instalación')
    if mode == 'demo' and (config_path or engine_dir):
        raise ValueError('--config y --engine-dir solo se usan en modo real')
    if config_path and engine_dir:
        raise ValueError('Usá --config o --engine-dir, no ambos')
    current = ETC / 'config.json'
    config = None
    if mode == 'real':
        if config_path:
            config = read_json(config_path)
            if current.exists() and config != read_json(current) and not replace:
                raise ValueError('Ya hay una configuración distinta. Para reemplazarla usá --replace-config')
        elif current.exists() and not engine_dir:
            config = read_json(current)
        else:
            config = automatic_config(engine_dir)
            if current.exists() and config != read_json(current) and not replace:
                raise ValueError('Ya hay una configuración distinta. Para reemplazarla usá --replace-config')
        validate_config(config, check_paths)
    for name in FILES:
        if not (SOURCE / name).is_file():
            raise ValueError(f'Falta el archivo {name}; ejecutá desde una copia completa del proyecto')
    return mode, config


def ensure_idle(port=8080, target_port=None):
    target_port = port if target_port is None else target_port
    active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=False).returncode == 0
    if not active:
        check_port_available(target_port)
        return
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/status', timeout=3) as response:
            status = json.load(response)
    except Exception as exc:
        raise ValueError('El servicio está activo pero no responde. No se reiniciará sin conocer el estado del respaldo') from exc
    if status.get('job', {}).get('state') not in ('idle', 'success', 'review', 'error'):
        raise ValueError('Hay un respaldo activo o un estado desconocido. Esperá antes de actualizar')
    if target_port != port:
        check_port_available(target_port)
    return True


def install(mode, config, display='web', framebuffer=None, port=8080):
    validate_port(port)
    import native_install
    if display == 'native':
        native_install.check_dependencies(framebuffer, install_missing=True)
    if mode == 'real' and not shutil.which('lsblk'):
        native_install.install_packages(['util-linux'])
        if not shutil.which('lsblk'):
            raise ValueError('util-linux se instaló pero no se encontró lsblk en PATH')
    previous = read_json(ETC / 'install.json') if (ETC / 'install.json').exists() else {}
    active = ensure_idle(selected_port(None, previous), port)
    native_install.stop()
    if active:
        subprocess.run(['systemctl', 'stop', SERVICE], check=True)
    APP.mkdir(parents=True, exist_ok=True)
    ETC.mkdir(parents=True, exist_ok=True)
    APP.chmod(0o755)
    ETC.chmod(0o755)
    # Copy only application files; preserve configuration and logs across updates.
    for name in FILES:
        target = APP / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o755)
        shutil.copyfile(SOURCE / name, target)
        target.chmod(0o644)
    if config is not None:
        target = ETC / 'config.json'
        if target.exists() and read_json(target) != config:
            backup = ETC / 'config.previous.json'
            shutil.copyfile(target, backup)
            backup.chmod(0o600)
        target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        target.chmod(0o600)
    (ETC / 'install.json').write_text(json.dumps({'mode': mode, 'display': display, 'framebuffer': framebuffer, 'port': port}) + '\n', encoding='utf-8')
    UNIT.write_text(service_text(mode, port), encoding='utf-8')
    UNIT.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', SERVICE], check=True)
    import time
    for _ in range(20):
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/status', timeout=1) as response:
                status = json.load(response)
            if status['demo'] != (mode == 'demo'):
                raise ValueError('El servicio arrancó con un modo inesperado')
            if display == 'native':
                native_install.install(framebuffer, port)
            else:
                native_install.disable()
            return
        except (OSError, KeyError):
            time.sleep(.5)
    raise ValueError(f'El servicio no responde. Revisá: journalctl -u {SERVICE} -n 50')


def main():
    parser = argparse.ArgumentParser(description='Instalador para Raspberry Pi OS/Linux con systemd')
    parser.add_argument('--mode', choices=('demo', 'real'))
    parser.add_argument('--config', type=Path, help='Configuración del motor real')
    parser.add_argument('--engine-dir', type=Path, help='Directorio del motor si no se encuentra automáticamente')
    parser.add_argument('--replace-config', action='store_true', help='Reemplazar configuración existente y guardar copia anterior')
    parser.add_argument('--dry-run', action='store_true', help='Mostrar plan sin escribir ni iniciar servicios')
    parser.add_argument('--display', choices=('web', 'native'), help='Interfaz nativa sin escritorio o navegador; conserva la opción instalada')
    parser.add_argument('--framebuffer', help='Dispositivo de pantalla SPI para Qt, por ejemplo /dev/fb1')
    parser.add_argument('--port', type=int, help='Puerto HTTP local; conserva el instalado, por defecto 8080')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error('Se necesita Python 3.10 o posterior')
    try:
        mode, config = plan(args.mode, args.config, args.replace_config, check_paths=not args.dry_run, engine_dir=args.engine_dir)
        previous = read_json(ETC / 'install.json') if (ETC / 'install.json').exists() else {}
        port = selected_port(args.port, previous)
        if args.port is None and 'port' not in previous and not previous and sys.platform == 'linux':
            for port in range(8080, 8101):
                try:
                    check_port_available(port)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError('No hay puertos libres entre 8080 y 8100; indicá --port')
        display = args.display or previous.get('display', 'native')
        framebuffer = args.framebuffer or previous.get('framebuffer')
        if display not in ('web', 'native'):
            raise ValueError('Interfaz inválida en los datos de instalación')
        if display == 'native':
            from native_install import validate_framebuffer
            if not framebuffer:
                framebuffer = automatic_framebuffer()
            validate_framebuffer(framebuffer, check_paths=False)
        elif args.framebuffer:
            raise ValueError('--framebuffer requiere --display native')
        print(f'Modo: {mode}\nAplicación: {APP}\nConfiguración: {ETC}\nServicio: {SERVICE}\nURL local: http://127.0.0.1:{port}')
        if config:
            print(f"Motor: {config['engine_dir']}\nDispositivos: detección automática al conectar; perfiles manuales opcionales")
        if args.dry_run:
            print('Al instalar se comprobarán las dependencias y apt instalará las faltantes: '
                  + ', '.join((['python3-pyqt6'] if display == 'native' else [])
                              + (['util-linux (lsblk)'] if mode == 'real' else [])))
            print('\nNo se modificó el sistema. Las rutas del motor se comprobarán al instalar.\n')
            print(service_text(mode, port))
            if display == 'native':
                from native_install import service_text as display_service
                print(display_service(framebuffer, port))
            return
        if sys.platform != 'linux' or not hasattr(os, 'geteuid') or os.geteuid() != 0:
            raise ValueError('Instalá en la Raspberry Pi con sudo python3 install.py')
        if not Path('/run/systemd/system').is_dir() or not shutil.which('systemctl'):
            raise ValueError('Se necesita un sistema iniciado con systemd')
        if not Path('/usr/bin/python3').is_file():
            raise ValueError('Se necesita Python en /usr/bin/python3')
        subprocess.run(['/usr/bin/python3', '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'], check=True)
        install(mode, config, display, framebuffer, port)
        print('\nInstalación completa. ' + ('La interfaz nativa inicia en la pantalla SPI.' if display == 'native' else f'Abrí http://127.0.0.1:{port} en el navegador de la Raspberry Pi.'))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
