"""Optional native display unit; no boot, driver, HDMI or network changes."""
from pathlib import Path
import re
import subprocess

SERVICE = 'little-backup-box-display.service'
UNIT = Path('/etc/systemd/system') / SERVICE


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


def check_dependencies(framebuffer):
    validate_framebuffer(framebuffer)
    result = subprocess.run(['/usr/bin/python3', '-c',
                             'from PyQt6 import QtWidgets, QtNetwork; '
                             'from PyQt6.QtCore import QLibraryInfo; '
                             'from pathlib import Path; '
                             'import sys; '
                             'sys.exit(0 if (Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) '
                             '/ "platforms/libqlinuxfb.so").is_file() else 1)'], check=False)
    if result.returncode:
        raise ValueError('Se necesita PyQt6 con el plugin LinuxFB. Instalá primero: sudo apt install python3-pyqt6')


def stop():
    if UNIT.exists():
        subprocess.run(['systemctl', 'stop', SERVICE], check=True)


def install(framebuffer, port=8080):
    UNIT.write_text(service_text(framebuffer, port), encoding='utf-8')
    UNIT.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', SERVICE], check=True)


def disable():
    if UNIT.exists():
        subprocess.run(['systemctl', 'disable', '--now', SERVICE], check=True)
