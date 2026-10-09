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
                install.install('real', new)
                self.assertEqual(install.read_json(etc / 'config.previous.json'), old)
                self.assertEqual(install.read_json(etc / 'config.json'), new)
                self.assertTrue((root / 'app/web/app.js').is_file())
                self.assertFalse((root / 'app/tests').exists())
                run.assert_any_call(['systemctl', 'enable', '--now', install.SERVICE], check=True)
