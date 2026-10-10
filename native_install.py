"""Optional native display unit; no boot, driver, HDMI or network changes."""
from pathlib import Path
import re
import shutil
import subprocess

SERVICE = 'little-backup-box-display.service'
UNIT = Path('/etc/systemd/system') / SERVICE
DISPLAY_ENV = Path('/etc/little-backup-box-screen/display.env')
GRAPHICS = Path('/sys/class/graphics')
INPUT_DEVICES = Path('/proc/bus/input/devices')
ADS7846_MATRIX = '0 -1.1375 1.083333 1.204412 0 -0.117647'


def configure_touch(framebuffer):
    # Keep existing calibration and backend choices, including on updates.
    if DISPLAY_ENV.exists():
        print(f'Configuración táctil existente conservada: {DISPLAY_ENV}')
        return
    frame = GRAPHICS / Path(framebuffer).name
    try:
        supported = ((frame / 'name').read_text().strip() == 'fb_ili9486'
                     and (frame / 'virtual_size').read_text().strip() == '480,320'
                     and 'Name="ADS7846 Touchscreen"' in INPUT_DEVICES.read_text())
    except OSError:
        supported = False
    if not supported:
        print('Sin perfil táctil automático para esta pantalla; se usa la detección de Qt.')
        return
    DISPLAY_ENV.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects a configuration written during detection.
    try:
        with DISPLAY_ENV.open('x', encoding='utf-8') as output:
            output.write('# ADS7846 + ILI9486 horizontal 480x320: perfil probado en la Raspberry Pi.\n'
                         '# Usa libinput; no forzar evdev para este táctil de un solo contacto.\n'
                         f'QT_QPA_LIBINPUT_TOUCH_MATRIX="{ADS7846_MATRIX}"\n')
    except FileExistsError:
        return
    DISPLAY_ENV.chmod(0o644)
    print('Calibración ADS7846/ILI9486 480x320 instalada con libinput.')


def validate_framebuffer(value, check_paths=True):
    if not isinstance(value, str) or not re.fullmatch(r'/dev/fb[0-9]+', value):
        raise ValueError('Indicá el framebuffer de la pantalla SPI: --framebuffer /dev/fbN')
    if check_paths and not Path(value).is_char_device():
        raise ValueError(f'{value} no es un dispositivo framebuffer. Revisá el controlador de la pantalla')


def service_text(framebuffer, port=8080):
    from install import validate_port
    validate_port(port)
    validate_framebuffer(framebuffer, False)
    return f'''[Unit]
Description=Little Backup Box - interfaz nativa SPI
After=little-backup-box-screen.service
Wants=little-backup-box-screen.service

[Service]
Type=simple
WorkingDirectory=/opt/little-backup-box-screen
ExecStart=/usr/bin/python3 /opt/little-backup-box-screen/native.py --port {port}
Environment=QT_QPA_PLATFORM=linuxfb:fb={framebuffer}
Environment=QT_QPA_FB_HIDECURSOR=1
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/little-backup-box-screen/display.env
DynamicUser=yes
SupplementaryGroups=video input
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
'''


def qt_available():
    result = subprocess.run(['/usr/bin/python3', '-c',
                             'from PyQt6 import QtWidgets, QtNetwork; '
                             'from PyQt6.QtCore import QLibraryInfo; '
                             'from pathlib import Path; '
                             'import sys; '
                             'sys.exit(0 if (Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) '
                             '/ "platforms/libqlinuxfb.so").is_file() else 1)'], check=False,
                            capture_output=True, text=True)
    return result.returncode == 0


def install_packages(packages):
    if not packages:
        return
    apt = shutil.which('apt-get')
    if not apt:
        raise ValueError('No se encontró apt-get. Instalá estas dependencias con el gestor de tu sistema: ' + ' '.join(packages))
    print('Instalando dependencias faltantes: ' + ', '.join(packages), flush=True)
    try:
        subprocess.run([apt, 'update'], check=True)
        subprocess.run([apt, 'install', '-y', *packages], check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError('No se pudieron instalar las dependencias. Revisá la salida de apt, la conexión y los repositorios; luego volvé a ejecutar el instalador') from exc


def check_dependencies(framebuffer, install_missing=False):
    validate_framebuffer(framebuffer)
    if qt_available():
        return
    if install_missing:
        install_packages(['python3-pyqt6'])
        if qt_available():
            return
        raise ValueError('PyQt6 se instaló pero el plugin LinuxFB no está disponible para /usr/bin/python3. Revisá los paquetes Qt del sistema')
    raise ValueError('Se necesita PyQt6 con el plugin LinuxFB. Instalá primero: sudo apt install python3-pyqt6')


def stop():
    if UNIT.exists():
        subprocess.run(['systemctl', 'stop', SERVICE], check=True)


def install(framebuffer, port=8080):
    configure_touch(framebuffer)
    UNIT.write_text(service_text(framebuffer, port), encoding='utf-8')
    UNIT.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', SERVICE], check=True)


def disable():
    if UNIT.exists():
        subprocess.run(['systemctl', 'disable', '--now', SERVICE], check=True)
