"""Install the touch frontend on Linux/systemd. No downloads or engine changes."""
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
FILES = ('server.py', 'web/index.html', 'web/app.js', 'web/style.css', 'LICENSE', 'README.md', 'config.example.json')


def validate_config(config, check_paths=True):
    if not isinstance(config, dict):
        raise ValueError('La configuración debe ser un objeto JSON')
    for key in ('engine_dir', 'files_root', 'python'):
        if not isinstance(config.get(key), str) or not config[key].startswith('/'):
            raise ValueError(f'{key} debe ser una ruta absoluta de Linux')
    identifiers = set()
    for group, allowed in [('sources', {'camera', 'anyusb', 'usb', 'internal', 'nvme'}),
                           ('destinations', {'usb', 'internal', 'nvme'})]:
        devices = config.get(group)
        if not isinstance(devices, list) or not devices:
            raise ValueError(f'{group} debe contener al menos un dispositivo')
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


def service_text(mode):
    extra = ' --config /etc/little-backup-box-screen/config.json' if mode == 'real' else ''
    identity = 'User=root\n' if mode == 'real' else 'DynamicUser=yes\nProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nNoNewPrivileges=yes\n'
    return f'''[Unit]
Description=Little Backup Box - pantalla tactil
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/little-backup-box-screen
ExecStart=/usr/bin/python3 /opt/little-backup-box-screen/server.py{extra}
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


def plan(mode=None, config_path=None, replace=False, check_paths=True):
    previous = read_json(ETC / 'install.json') if (ETC / 'install.json').exists() else {}
    mode = mode or ('real' if config_path else previous.get('mode', 'demo'))
    if mode not in ('demo', 'real'):
        raise ValueError('Modo inválido en los datos de instalación')
    if mode == 'demo' and config_path:
        raise ValueError('--config solo se usa en modo real')
    current = ETC / 'config.json'
    config = None
    if mode == 'real':
        if config_path:
            config = read_json(config_path)
            if current.exists() and config != read_json(current) and not replace:
                raise ValueError('Ya hay una configuración distinta. Para reemplazarla usá --replace-config')
        elif current.exists():
            config = read_json(current)
        else:
            raise ValueError('Modo real: indicá --config config.local.json')
        validate_config(config, check_paths)
    for name in FILES:
        if not (SOURCE / name).is_file():
            raise ValueError(f'Falta el archivo {name}; ejecutá desde una copia completa del proyecto')
    return mode, config


def ensure_idle():
    active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=False).returncode == 0
    try:
        with urlopen('http://127.0.0.1:8080/api/status', timeout=3) as response:
            status = json.load(response)
    except Exception as exc:
        if active:
            raise ValueError('El servicio está activo pero no responde. No se reiniciará sin conocer el estado del respaldo') from exc
        # Check for another listener, even when our service is not active.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 8080)) == 0:
                raise ValueError('El puerto 8080 está ocupado por otro servidor')
        return
    if not active:
        raise ValueError('Hay otra instancia en el puerto 8080. Cerrala antes de instalar')
    if status.get('job', {}).get('state') not in ('idle', 'success', 'review', 'error'):
        raise ValueError('Hay un respaldo activo o un estado desconocido. Esperá antes de actualizar')
    return True


def install(mode, config):
    if ensure_idle():
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
    (ETC / 'install.json').write_text(json.dumps({'mode': mode}) + '\n', encoding='utf-8')
    UNIT.write_text(service_text(mode), encoding='utf-8')
    UNIT.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', SERVICE], check=True)
    import time
    for _ in range(20):
        try:
            with urlopen('http://127.0.0.1:8080/api/status', timeout=1) as response:
                status = json.load(response)
            if status['demo'] != (mode == 'demo'):
                raise ValueError('El servicio arrancó con un modo inesperado')
            return
        except (OSError, KeyError):
            time.sleep(.5)
    raise ValueError(f'El servicio no responde. Revisá: journalctl -u {SERVICE} -n 50')


def main():
    parser = argparse.ArgumentParser(description='Instalador para Raspberry Pi OS/Linux con systemd')
    parser.add_argument('--mode', choices=('demo', 'real'))
    parser.add_argument('--config', type=Path, help='Configuración del motor real')
    parser.add_argument('--replace-config', action='store_true', help='Reemplazar configuración existente y guardar copia anterior')
    parser.add_argument('--dry-run', action='store_true', help='Mostrar plan sin escribir ni iniciar servicios')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error('Se necesita Python 3.10 o posterior')
    try:
        mode, config = plan(args.mode, args.config, args.replace_config, check_paths=not args.dry_run)
        print(f'Modo: {mode}\nAplicación: {APP}\nConfiguración: {ETC}\nServicio: {SERVICE}\nURL local: http://127.0.0.1:8080')
        if args.dry_run:
            print('\nNo se modificó el sistema. Las rutas del motor se comprobarán al instalar.\n')
            print(service_text(mode))
            return
        if sys.platform != 'linux' or not hasattr(os, 'geteuid') or os.geteuid() != 0:
            raise ValueError('Instalá en la Raspberry Pi con sudo python3 install.py')
        if not Path('/run/systemd/system').is_dir() or not shutil.which('systemctl'):
            raise ValueError('Se necesita un sistema iniciado con systemd')
        if not Path('/usr/bin/python3').is_file():
            raise ValueError('Se necesita Python en /usr/bin/python3')
        subprocess.run(['/usr/bin/python3', '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'], check=True)
        install(mode, config)
        print('\nInstalación completa. Abrí http://127.0.0.1:8080 en el navegador de la Raspberry Pi.')
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
