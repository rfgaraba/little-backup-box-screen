import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import Engine, command


class GatewayTests(unittest.TestCase):
    def test_identified_card_uses_usb_instead_of_dynamic_anyusb(self):
        argv = command({'engine_dir': '/engine'},
                       {'id': 'card', 'engine': 'anyusb', 'preset': '--uuid a'},
                       {'id': 'ssd', 'engine': 'usb', 'preset': '--uuid b'}, True)
        self.assertEqual(argv[argv.index('--SourceName') + 1], 'usb')
        self.assertEqual(argv[argv.index('--TargetName') + 1], 'usb')
        self.assertIn('--uuid a', argv)
        with self.assertRaises(ValueError):
            command({'engine_dir': '/engine'},
                    {'id': 'card', 'engine': 'anyusb', 'preset': '--uuid a'},
                    {'id': 'ssd', 'engine': 'usb'}, True)

    def test_engine_internal_error_is_reported_even_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tmp').mkdir()
            upstream = root / 'tmp/little-backup-box.log'
            upstream.write_text('Registro anterior\n')
            engine = Engine({'engine_dir': tmp})
            def finish():
                with upstream.open('a') as log:
                    log.write('Invalid\nmode\ncombination\n')
                return 0
            with patch.dict('os.environ', {'LBB_SCREEN_STATE_DIR': str(root)}), patch('server.subprocess.Popen') as spawn:
                spawn.return_value.wait.side_effect = finish
                engine.run(['fake-engine'])
            self.assertEqual(engine.status()['job']['state'], 'error')
            self.assertIn('No se copió', engine.status()['job']['message'])
            captured = (root / 'engine.log').read_text()
            self.assertIn('Invalid', captured)
            self.assertNotIn('Registro anterior', captured)
    def test_real_devices_are_discovered_without_configured_uuids(self):
        source = {'id': 'auto:a', 'engine': 'anyusb', 'preset': '--uuid a', 'disk': '/dev/sda', 'sd': True}
        target = {'id': 'auto:b', 'engine': 'usb', 'preset': '--uuid b', 'disk': '/dev/sdb', 'sd': False}
        found = {'sources': [source, target], 'destinations': [dict(source, engine='usb'), target]}
        engine = Engine({'engine_dir': '/engine'})
        with patch('server.discover', return_value=found):
            devices = engine.devices()
        self.assertEqual(devices['automatic'], {'source': 'auto:a', 'destination': 'auto:b'})
        self.assertIn('--uuid b', command(engine.config, devices['sources'][0], devices['destinations'][1], True))

    def test_command_uses_safe_explicit_arguments(self):
        argv = command({'engine_dir': '/engine'},
                       {'id': 'card', 'engine': 'anyusb', 'preset': '--uuid a'},
                       {'id': 'disk', 'engine': 'usb', 'preset': '--uuid b'}, True)
        self.assertIn(str(Path('/engine') / 'backup.py'), argv)
        self.assertEqual(argv[argv.index('--move-files') + 1], 'False')
        self.assertEqual(argv[argv.index('--power-off') + 1], 'False')
        self.assertEqual(argv[argv.index('--checksum') + 1], 'True')
        self.assertIn('--uuid a', argv)

    def test_rejects_aliases_and_unsupported_types(self):
        for source, target in [
            ({'id': 'a', 'engine': 'usb'}, {'id': 'b', 'engine': 'usb'}),
            ({'id': 'a', 'engine': 'usb', 'preset': 'same'}, {'id': 'b', 'engine': 'nvme', 'preset': 'same'}),
            ({'id': 'a', 'engine': ';shutdown'}, {'id': 'b', 'engine': 'usb'}),
        ]:
            with self.assertRaises(ValueError):
                command({'engine_dir': '/engine'}, source, target, True)

    def test_duplicate_job_is_rejected(self):
        engine = Engine()
        engine.job['state'] = 'running'
        with self.assertRaises(ValueError):
            engine.start({'source': 'card', 'destination': 'ssd'})

    def test_demo_lifecycle(self):
        engine = Engine()
        with patch('server.time.sleep'):
            engine.run(None)
        self.assertEqual(engine.status()['job']['state'], 'success')
        self.assertIn('no se copiaron', engine.status()['job']['message'])

    def test_real_zero_exit_requires_review(self):
        engine = Engine({'engine_dir': '.'})
        with patch('server.subprocess.Popen') as spawn:
            spawn.return_value.wait.return_value = 0
            engine.run(['fake-engine'])
            self.assertFalse(spawn.call_args.kwargs['shell'])
        self.assertEqual(engine.status()['job']['state'], 'review')

    def test_files_pagination_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                (root / f'{i}.jpg').write_text('photo')
            engine = Engine({'files_root': tmp})
            self.assertEqual(len(engine.files('', 0)['entries']), 2)
            self.assertEqual(engine.files('', 10)['page'], 2)
            with self.assertRaises(ValueError):
                engine.files('../', 0)


if __name__ == '__main__':
    unittest.main()
