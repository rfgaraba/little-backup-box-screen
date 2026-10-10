"""Linux storage discovery and upstream Comitup Wi-Fi integration."""
import json
import subprocess
import secrets
import threading


def discover():
    result = subprocess.run(['lsblk', '--json', '--paths', '--output',
                             'NAME,TYPE,TRAN,RM,MODEL,UUID,FSTYPE,MOUNTPOINTS'],
                            capture_output=True, text=True, check=True, timeout=5)
    sources, destinations = [], []
    def protected(n):
        return any(m in ('/', '/boot', '/boot/firmware') for m in n.get('mountpoints') or []) or any(protected(c) for c in n.get('children', []))
    def visit(n, disk):
        sd = disk.get('tran') == 'mmc' or disk.get('rm') in (True, 1, '1') or any(
            w in str(disk.get('model', '')).lower() for w in ('sd reader', 'sd/mmc', 'card reader'))
        if n.get('uuid') and n.get('fstype') not in (None, 'swap', 'crypto_LUKS', 'LVM2_member') and (sd or disk.get('tran') == 'usb'):
            d = {'id': 'auto:' + n['uuid'], 'label': f"{n['name']} · {disk.get('model') or 'USB/SD'}",
                 'engine': 'anyusb' if sd else 'usb', 'preset': '--uuid ' + n['uuid'], 'disk': disk['name'], 'sd': sd}
            sources.append(d)
            destinations.append(dict(d, engine='usb'))
        for c in n.get('children', []):
            visit(c, disk)
    for disk in json.loads(result.stdout)['blockdevices']:
        if not protected(disk):
            visit(disk, disk)
    cards = [d for d in sources if d['sd']]
    disks = [d for d in destinations if not d['sd']]
    return {'sources': sources, 'destinations': destinations, 'automatic': {
        'source': cards[0]['id'] if len(cards) == 1 else None,
        'destination': disks[0]['id'] if len(disks) == 1 else None}}


class Wifi:
    HOTSPOT_UUID = 'e783352b-a1eb-43bc-9adb-b0339b539723'
    HOTSPOT_NAME = 'little-backup-box-screen'

    def __init__(self):
        self.lock = threading.RLock()

    def nm(self, *args, check=True):
        return subprocess.run(['nmcli', '--wait', '10', *args], capture_output=True,
                              text=True, check=check, timeout=15).stdout.strip()

    def forced(self):
        try:
            return self.HOTSPOT_UUID in self.nm('-g', 'UUID', 'connection', 'show', '--active').splitlines()
        except (OSError, subprocess.SubprocessError):
            return False

    def service(self, action):
        subprocess.run(['systemctl', action, 'comitup.service'], capture_output=True,
                       check=True, timeout=20)

    def enable_hotspot(self):
        if self.forced():
            return
        # Verify upstream is available before temporarily handing Wi-Fi to NM.
        self.interface().get_info()
        devices = self.nm('-t', '-f', 'DEVICE,TYPE', 'device', 'status').splitlines()
        interfaces = [line.rsplit(':', 1)[0] for line in devices if line.endswith(':wifi')]
        if not interfaces:
            raise ValueError('No se encontró un adaptador Wi-Fi')
        iface = interfaces[0]
        profiles = self.nm('-g', 'UUID', 'connection', 'show').splitlines()
        if self.HOTSPOT_UUID not in profiles:
            # A separate profile preserves every saved upstream network and password.
            self.nm('connection', 'add', 'type', 'wifi', 'ifname', iface,
                    'con-name', self.HOTSPOT_NAME, 'connection.uuid', self.HOTSPOT_UUID,
                    'ssid', self.HOTSPOT_NAME, '802-11-wireless.mode', 'ap',
                    'ipv4.method', 'shared', 'ipv6.method', 'disabled',
                    'wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', secrets.token_hex(6),
                    'connection.autoconnect', 'no')
        try:
            self.service('stop')
            self.nm('connection', 'up', 'uuid', self.HOTSPOT_UUID, 'ifname', iface)
        except Exception:
            self.service('start')
            raise

    def resume(self):
        active = self.forced()
        if active:
            self.nm('connection', 'down', 'uuid', self.HOTSPOT_UUID)
        try:
            self.service('start')
        except Exception:
            if active:
                self.nm('connection', 'up', 'uuid', self.HOTSPOT_UUID)
            raise

    def interface(self):
        import dbus
        name = 'com.github.davesteele.comitup'
        return dbus.Interface(dbus.SystemBus().get_object(name, '/' + name.replace('.', '/')), name)

    def status(self):
        with self.lock:
            return self.read_status()

    def read_status(self):
        try:
            if self.forced():
                return {'available': True, 'state': 'HOTSPOT', 'connection': '',
                        'hotspot': self.HOTSPOT_NAME, 'mode': 'manual', 'forced': True,
                        'password': self.nm('--show-secrets', '-g', '802-11-wireless-security.psk',
                                            'connection', 'show', 'uuid', self.HOTSPOT_UUID),
                        'address': self.nm('-g', 'IP4.ADDRESS', 'connection', 'show', 'uuid', self.HOTSPOT_UUID),
                        'networks': []}
            api = self.interface()
            state, connection = api.state()
            info = api.get_info()
            return {'available': True, 'state': str(state), 'connection': str(connection),
                    'hotspot': str(info.get('apname', '')), 'mode': str(info.get('imode', 'single')), 'forced': False,
                    'networks': [{'ssid': str(n['ssid']), 'security': str(n['security'])} for n in api.access_points()]}
        except Exception:
            return {'available': False, 'message': 'Wi-Fi requiere Comitup activo y python3-dbus.'}

    def apply(self, data):
        with self.lock:
            self.change(data)

    def change(self, data):
        try:
            if data.get('action') == 'connect':
                if self.forced():
                    raise ValueError('Primero tocá Volver a Wi-Fi para salir del hotspot')
                api = self.interface()
                ssid, password = data.get('ssid'), data.get('password', '')
                if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or not isinstance(password, str):
                    raise ValueError('Red o contraseña inválida')
                api.connect(ssid, password)
            elif data.get('action') == 'hotspot':
                self.enable_hotspot()
            elif data.get('action') == 'resume':
                self.resume()
            else:
                raise ValueError('Acción Wi-Fi inválida')
        except ValueError:
            raise
        except Exception:
            raise ValueError('No se pudo configurar Wi-Fi; revisá Comitup, NetworkManager y sus permisos') from None
