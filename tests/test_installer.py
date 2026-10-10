import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import install


def config():
    return {'engine_dir': '/engine', 'files_root': '/media/backup', 'python': '/usr/bin/python3',
            'sources': [{'id': 'camera', 'label': 'Cámara', 'engine': 'camera'}],
            'destinations': [{'id': 'disk', 'label': 'SSD', 'engine': 'usb', 'preset': '--uuid actual'}]}


class InstallerTests(unittest.TestCase):
    def test_automatic_config_needs_no_connected_disks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'backup.py').write_text('')
            data = install.automatic_config(root)
            self.assertEqual(data['engine_dir'], str(root.resolve()))
            self.assertEqual(data['sources'], [])
            self.assertEqual(data['destinations'], [])
            with self.assertRaises(ValueError):
                install.automatic_config(root / 'missing')

    def test_config_allows_automatic_discovery_without_profiles(self):
        data = config()
        data['sources'] = []
        data['destinations'] = []
        install.validate_config(data, False)
        del data['sources']
        del data['destinations']
        install.validate_config(data, False)

    def test_new_real_install_generates_config_and_demo_remains_explicit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(install, 'ETC', Path(tmp)), patch('install.automatic_config', return_value=config()) as detect:
            self.assertEqual(install.plan(check_paths=False), ('real', config()))
            detect.assert_called_once_with(None)
            self.assertEqual(install.plan(mode='demo', check_paths=False), ('demo', None))

    def test_port_selection_preserves_updates_and_validates(self):
        self.assertEqual(install.selected_port(None, {}), 8080)
        self.assertEqual(install.selected_port(None, {'port': 8081}), 8081)
        self.assertEqual(install.selected_port(9090, {'port': 8081}), 9090)
        for value in (0, -1, 65536, True, '8081'):
            with self.assertRaises(ValueError):
                install.validate_port(value)

    def test_new_install_checks_only_selected_port(self):
        with patch('install.subprocess.run') as run, patch('install.check_port_available') as check, patch('install.urlopen') as request:
            run.return_value.returncode = 3
            install.ensure_idle(8080, 8081)
            check.assert_called_once_with(8081)
            request.assert_not_called()

    def test_port_change_checks_old_job_and_new_listener(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"job":{"state":"idle"}}'
        with patch('install.subprocess.run') as run, patch('install.check_port_available') as check, patch('install.urlopen', return_value=response) as request:
            run.return_value.returncode = 0
            self.assertTrue(install.ensure_idle(8081, 9090))
            request.assert_called_once_with('http://127.0.0.1:8081/api/status', timeout=3)
            check.assert_called_once_with(9090)

    def test_demo_service_is_unprivileged_and_real_uses_config(self):
        self.assertIn('DynamicUser=yes', install.service_text('demo'))
        self.assertNotIn('--config', install.service_text('demo'))
        self.assertIn('User=root', install.service_text('real'))
        self.assertIn('--config /etc/', install.service_text('real'))
        self.assertIn('StateDirectory=', install.service_text('real'))

    def test_config_rejects_placeholders_and_duplicate_ids(self):
        data = config()
        data['destinations'][0]['preset'] = '--uuid REEMPLAZAR-UUID'
        with self.assertRaises(ValueError):
            install.validate_config(data, False)
        data = config()
        data['destinations'][0]['id'] = 'camera'
        with self.assertRaises(ValueError):
            install.validate_config(data, False)

    def test_update_preserves_mode_and_requires_explicit_config_replacement(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(install, 'ETC', Path(tmp)):
            root = Path(tmp)
            (root / 'install.json').write_text('{"mode":"real"}')
            (root / 'config.json').write_text(json.dumps(config()))
            self.assertEqual(install.plan(check_paths=False), ('real', config()))
            changed = config(); changed['destinations'][0]['label'] = 'Otro SSD'
            supplied = root / 'new.json'; supplied.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                install.plan(config_path=supplied, check_paths=False)
            self.assertEqual(install.plan(config_path=supplied, replace=True, check_paths=False)[1], changed)

    def test_running_or_unknown_job_blocks_install(self):
        for state in ('running', 'unknown'):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({'job': {'state': state}}).encode()
            with patch('install.subprocess.run') as run, patch('install.urlopen', return_value=response):
                run.return_value.returncode = 0
                with self.assertRaises(ValueError):
                    install.ensure_idle()

    def test_install_copies_only_app_files_and_preserves_old_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); etc = root / 'etc'; etc.mkdir()
            old = config(); (etc / 'config.json').write_text(json.dumps(old))
            new = config(); new['destinations'][0]['label'] = 'Nuevo'
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"demo":false}'
            with patch.object(install, 'APP', root / 'app'), patch.object(install, 'ETC', etc), \
                 patch.object(install, 'UNIT', root / 'unit.service'), patch('install.ensure_idle'), \
                 patch('install.subprocess.run') as run, patch('install.urlopen', return_value=response):
                install.install('real', new, port=8081)
                self.assertEqual(install.read_json(etc / 'install.json')['port'], 8081)
                self.assertIn('--port 8081', (root / 'unit.service').read_text())
                install.urlopen.assert_called_once_with('http://127.0.0.1:8081/api/status', timeout=1)
                self.assertEqual(install.read_json(etc / 'config.previous.json'), old)
                self.assertEqual(install.read_json(etc / 'config.json'), new)
                self.assertTrue((root / 'app/web/app.js').is_file())
                self.assertFalse((root / 'app/tests').exists())
                run.assert_any_call(['systemctl', 'enable', '--now', install.SERVICE], check=True)
