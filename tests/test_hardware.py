import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from hardware import discover, Wifi, network_info
from server import Engine


def disk(name, transport, uuid, mount=None, model=''):
    return {'name': name, 'tran': transport, 'model': model, 'children': [
        {'name': name + '1', 'uuid': uuid, 'fstype': 'exfat', 'mountpoints': [mount]}]}


class HardwareTests(unittest.TestCase):
    def test_network_info_reports_real_wifi_and_default_interface(self):
        interfaces = [{'ifname': 'lo', 'addr_info': []},
                      {'ifname': 'wlan0', 'operstate': 'UP', 'address': 'aa:bb:cc:dd:ee:ff',
                       'addr_info': [{'family': 'inet', 'scope': 'global', 'local': '192.168.68.78'}]}]
        responses = [Mock(stdout=json.dumps(interfaces)), Mock(stdout='[{"dev":"wlan0","metric":600}]')]
        with patch('hardware.subprocess.run', side_effect=responses), patch('hardware.socket.gethostname', return_value='lbb'), patch('hardware.Path.exists', return_value=True), patch('hardware.Path.read_text', return_value='wlan0: 0000 70. -23. -256\n'):
            info = network_info()
        self.assertEqual(info['hostname'], 'lbb')
        self.assertEqual(info['ip'], '192.168.68.78')
        self.assertEqual(info['mac'], 'aa:bb:cc:dd:ee:ff')
        self.assertEqual(info['wifi'], {'state': 'connected', 'signal': 100})

    def test_network_info_without_network_tools_is_still_readable(self):
        with patch('hardware.subprocess.run', side_effect=FileNotFoundError), patch('hardware.socket.gethostname', return_value='lbb'):
            info = network_info()
        self.assertEqual(info['hostname'], 'lbb')
        self.assertEqual(info['wifi']['state'], 'unavailable')
        self.assertEqual(info['ip'], '')

    def scan(self, disks):
        with patch('hardware.subprocess.run', return_value=Mock(stdout=json.dumps({'blockdevices': disks}))):
            return discover()

    def test_system_disk_excluded_and_sd_usb_selected(self):
        found = self.scan([disk('/dev/mmcblk0', 'mmc', 'OS', '/'),
                           disk('/dev/sda', 'usb', 'DISK'), disk('/dev/sdb', 'usb', 'CARD', model='SD/MMC Reader')])
        self.assertEqual(found['automatic'], {'source': 'auto:CARD', 'destination': 'auto:DISK'})
        self.assertNotIn('auto:OS', [d['id'] for d in found['sources']])

    def test_ambiguous_destinations_and_removal(self):
        found = self.scan([disk('/dev/sda', 'usb', 'A'), disk('/dev/sdb', 'usb', 'B')])
        self.assertIsNone(found['automatic']['destination'])
        self.assertIsNone(found['automatic']['source'])
        self.assertEqual(self.scan([])['sources'], [])

    def test_generic_removable_reader_proposed_as_source(self):
        reader = disk('/dev/sdb', 'usb', 'SD')
        reader['rm'] = True
        found = self.scan([disk('/dev/sda', 'usb', 'SSD'), reader])
        self.assertEqual(found['automatic'], {'source': 'auto:SD', 'destination': 'auto:SSD'})

    def test_manual_profiles_when_detection_fails(self):
        engine = Engine({'sources': [{'id': 'card', 'label': 'SD'}], 'destinations': [{'id': 'disk', 'label': 'SSD'}]})
        with patch('server.discover', side_effect=FileNotFoundError):
            self.assertEqual(engine.devices()['sources'][0]['id'], 'card')
            self.assertIn('detection_error', engine.devices())

    def test_same_physical_disk_rejected(self):
        engine = Engine({'sources': [], 'destinations': [], 'engine_dir': '.'})
        source = {'id': 'auto:A', 'disk': '/dev/sda'}
        target = {'id': 'auto:B', 'disk': '/dev/sda'}
        with patch.object(engine, 'devices', return_value={'sources': [source], 'destinations': [target]}):
            with self.assertRaisesRegex(ValueError, 'mismo disco'):
                engine.start({'source': 'auto:A', 'destination': 'auto:B'})

    def test_wifi_connect_does_not_delete_saved_networks(self):
        wifi = Wifi()
        api = Mock()
        api.state.return_value = ('CONNECTED', 'Hotel')
        with patch.object(wifi, 'interface', return_value=api), patch.object(wifi, 'forced', return_value=False):
            wifi.apply({'action': 'connect', 'ssid': 'Hotel', 'password': 'secret'})
            api.connect.assert_called_once_with('Hotel', 'secret')
            api.delete_connection.assert_not_called()
            with self.assertRaises(ValueError):
                wifi.apply({'action': 'connect', 'ssid': ''})

    def test_manual_hotspot_keeps_profiles_and_pauses_comitup(self):
        wifi = Wifi()
        def nm(*args, **kwargs):
            if args == ('-t', '-f', 'DEVICE,TYPE', 'device', 'status'):
                return 'wlan0:wifi'
            return ''
        with patch.object(wifi, 'forced', return_value=False), patch.object(wifi, 'interface') as api, \
             patch.object(wifi, 'nm', side_effect=nm) as commands, patch.object(wifi, 'service') as service:
            wifi.apply({'action': 'hotspot'})
            service.assert_called_once_with('stop')
            commands.assert_any_call('connection', 'up', 'uuid', wifi.HOTSPOT_UUID, 'ifname', 'wlan0')
            for call in commands.call_args_list:
                self.assertNotIn('delete', call.args)
            api.return_value.delete_connection.assert_not_called()
            create = next(c for c in commands.call_args_list if 'add' in c.args)
            self.assertIn('connection.autoconnect', create.args)
            self.assertIn('no', create.args)

    def test_hotspot_failure_restores_comitup(self):
        wifi = Wifi()
        def nm(*args, **kwargs):
            if args == ('-t', '-f', 'DEVICE,TYPE', 'device', 'status'):
                return 'wlan0:wifi'
            if 'up' in args:
                raise subprocess.CalledProcessError(1, 'nmcli')
            return wifi.HOTSPOT_UUID
        with patch.object(wifi, 'forced', return_value=False), patch.object(wifi, 'interface'), \
             patch.object(wifi, 'nm', side_effect=nm), patch.object(wifi, 'service') as service:
            with self.assertRaises(ValueError):
                wifi.apply({'action': 'hotspot'})
            self.assertEqual([c.args[0] for c in service.call_args_list], ['stop', 'start'])

    def test_resume_deactivates_only_own_profile(self):
        wifi = Wifi()
        with patch.object(wifi, 'forced', return_value=True), patch.object(wifi, 'nm') as nm, \
             patch.object(wifi, 'service') as service:
            wifi.apply({'action': 'resume'})
            nm.assert_called_once_with('connection', 'down', 'uuid', wifi.HOTSPOT_UUID)
            service.assert_called_once_with('start')

    def test_hotspot_repeated_activation_is_idempotent(self):
        wifi = Wifi()
        with patch.object(wifi, 'forced', return_value=True), patch.object(wifi, 'service') as service:
            wifi.apply({'action': 'hotspot'})
            service.assert_not_called()

    def test_wifi_unavailable(self):
        with patch.object(Wifi, 'interface', side_effect=ImportError):
            self.assertFalse(Wifi().status()['available'])
