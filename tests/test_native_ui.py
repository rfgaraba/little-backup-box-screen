"""Native client integration and touch layout; requires PyQt6, no physical LCD."""
import importlib.util
import os
import threading
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PyQt6') is not None


@unittest.skipUnless(HAS_QT, 'Instalar PyQt6 para validar la interfaz nativa')
class NativeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from http.server import ThreadingHTTPServer
        from server import Engine, Handler
        import native
        cls.app = QApplication.instance() or QApplication([])
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.engine = Engine()
        cls.old_base = native.BASE
        native.BASE = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        import native
        native.BASE = cls.old_base
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def wait_for(self, predicate):
        from PyQt6.QtTest import QTest
        deadline = time.monotonic() + 6
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(predicate())

    def assert_layout(self, screen):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QPushButton
        self.app.processEvents()
        for button in screen.findChildren(QPushButton):
            if button.isVisible():
                self.assertGreaterEqual(button.width(), 48)
                self.assertGreaterEqual(button.height(), 48)
                position = button.mapTo(screen, QPoint(0, 0))
                self.assertGreaterEqual(position.x(), 0)
                self.assertGreaterEqual(position.y(), 0)
                self.assertLessEqual(position.x() + button.width(), 480)
                self.assertLessEqual(position.y() + button.height(), 320)

    def test_native_copy_navigation_settings_and_files(self):
        from native import Screen
        screen = Screen()
        screen.show()
        try:
            self.wait_for(lambda: screen.status is not None and bool(screen.devices['sources']))
            self.assertEqual(screen.tab, 'Copiar')
            self.assertEqual(screen.step, -1)
            self.assert_layout(screen)
            screen.new_job()
            self.assert_layout(screen)
            screen.manual_copy()
            screen.choose(screen.devices['sources'][0])
            self.assert_layout(screen)
            screen.choose(screen.devices['destinations'][0])
            self.assert_layout(screen)
            screen.start_job()
            self.wait_for(lambda: screen.step == 3)
            screen.switch('Ajustes')
            self.assert_layout(screen)
            screen.show_setting('Copia')
            screen.toggle_checksum()
            self.wait_for(lambda: not screen.status['checksum'])
            screen.switch('Archivos')
            self.wait_for(lambda: len(screen.files['entries']) == 2)
            self.assert_layout(screen)
            screen.change_page(1)
            self.wait_for(lambda: screen.files['page'] == 1)
            screen.open_entry(screen.files['entries'][0])
            self.assert_layout(screen)
            self.wait_for(lambda: screen.status['job']['state'] == 'success')
            screen.switch('Estado')
            self.assertIn('no se copiaron', screen.status['job']['message'])
            self.assert_layout(screen)
        finally:
            screen.timer.stop()
            screen.close()
            screen.deleteLater()
            self.app.processEvents()

    def test_touch_keyboard_fits_screen_and_masks_password(self):
        from native import Screen, TouchKeyboard
        from PyQt6.QtWidgets import QLineEdit
        screen = Screen()
        keyboard = TouchKeyboard('Contraseña', screen, True)
        keyboard.show()
        try:
            self.app.processEvents()
            self.assertEqual(keyboard.field.echoMode(), QLineEdit.EchoMode.Password)
            self.assert_layout(keyboard)
            keyboard.next_page()
            self.app.processEvents()
            self.assert_layout(keyboard)
        finally:
            keyboard.close()
            screen.timer.stop()
            screen.close()
            keyboard.deleteLater()
            screen.deleteLater()

    def test_info_settings_and_wifi_indicator_fit_the_screen(self):
        from native import Screen
        from PyQt6.QtWidgets import QPushButton
        screen = Screen()
        screen.show()
        try:
            self.wait_for(lambda: screen.status is not None and bool(screen.info))
            screen.status['demo'] = False
            screen.switch('Ajustes')
            self.assertNotIn('MOTOR REAL', screen.mode.text())
            self.assert_layout(screen)
            self.assertEqual([screen.content.itemAt(i).layout().itemAt(j).widget().full_text
                              for i in (1, 2) for j in (0, 1)], ['Info', 'Copia', 'Wi-Fi', 'Sistema'])
            screen.show_setting('Info')
            self.assert_layout(screen)
            for state in ('connected', 'connecting', 'disconnected', 'unavailable'):
                screen.wifi_indicator.set_state({'state': state, 'signal': 100})
                self.assertIn('Wi-Fi', screen.wifi_indicator.accessibleName())
                self.assertFalse(screen.wifi_indicator.grab().isNull())
        finally:
            screen.timer.stop()
            screen.close()
            screen.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
