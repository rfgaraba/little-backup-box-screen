"""Native 480x320 touch client. The backup service owns all transfer jobs."""
import argparse
import json
import sys
from urllib.parse import urlencode

from PyQt6.QtCore import QByteArray, Qt, QTimer, QUrl
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

BASE = 'http://127.0.0.1:8080'


class TouchButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.full_text = text
        self.setAccessibleName(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(QFontMetrics(self.font()).elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, max(1, self.width() - 20)))


class Screen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Little Backup Box')
        self.setFixedSize(480, 320)
        self.network = QNetworkAccessManager(self)
        self.status = None
        self.devices = {'sources': [], 'destinations': []}
        self.tab, self.step, self.page = 'Estado', 0, 0
        self.source = self.destination = self.detail = self.setting = None
        self.path, self.error = '', ''
        self.files = {'entries': [], 'page': 0, 'pages': 1}
        self.pending = False
        self.polling = False
        self.file_request = 0
        self.files_loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        self.mode = QLabel('CONECTANDO')
        self.mode.setFixedHeight(20)
        layout.addWidget(self.mode)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(4)
        layout.addWidget(self.body, 1)
        nav = QHBoxLayout()
        nav.setSpacing(4)
        for name in ('Estado', 'Copiar', 'Archivos', 'Ajustes'):
            nav.addWidget(self.button(name, lambda n=name: self.switch(n)))
        layout.addLayout(nav)
        self.setStyleSheet('''
            QWidget { background: #101c2a; color: #edf4fa; font-size: 15px; }
            QPushButton { background: #253b50; border: 1px solid #53718d;
                border-radius: 6px; padding: 2px 8px; }
            QPushButton:pressed { background: #397b97; }
            QPushButton:disabled { color: #7d8b98; }
            QProgressBar { border: 1px solid #53718d; text-align: center; }
            QProgressBar::chunk { background: #39bba6; }
        ''')
        self.render()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def button(self, text, action):
        b = TouchButton(text)
        b.setFixedHeight(48)
        b.setMinimumWidth(48)
        b.clicked.connect(lambda checked=False: action())
        return b

    def request(self, path, callback, data=None, failure=None):
        request = QNetworkRequest(QUrl(BASE + path))
        request.setTransferTimeout(5000)
        if data is None:
            reply = self.network.get(request)
        else:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
            reply = self.network.post(request, QByteArray(json.dumps(data).encode()))

        def finished():
            try:
                raw = bytes(reply.readAll())
                if reply.error() != reply.NetworkError.NoError and not raw:
                    raise ValueError('Sin conexión con el servidor')
                payload = json.loads(raw)
                if reply.error() != reply.NetworkError.NoError:
                    raise ValueError(payload.get('error', 'Sin conexión con el servidor'))
                callback(payload)
            except (ValueError, TypeError, KeyError) as exc:
                self.error = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Respuesta inválida del servidor'
                if failure:
                    failure()
                self.render()
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)

    def refresh(self):
        if self.polling:
            return
        self.polling = True

        def status(data):
            self.polling = False
            changed = data != self.status or self.error == 'Sin conexión con el servidor'
            self.status = data
            if self.error == 'Sin conexión con el servidor':
                self.error = ''
            if changed:
                self.render()
            if not self.devices['sources']:
                self.request('/api/devices', self.set_devices)
        self.request('/api/status', status, failure=lambda: setattr(self, 'polling', False))

    def set_devices(self, data):
        self.devices = data
        self.render()

    def switch(self, tab):
        self.tab, self.page = tab, 0
        self.detail = self.setting = None
        self.error = ''
        if tab == 'Archivos':
            self.load_files()
        self.render()

    def label(self, text):
        label = QLabel()
        metrics = QFontMetrics(label.font())
        lines = text.splitlines()[:2] or ['']
        label.setText('\n'.join(metrics.elidedText(line, Qt.TextElideMode.ElideRight, 450) for line in lines))
        label.setAccessibleName(text)
        label.setFixedHeight(22 * len(lines))
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.content.addWidget(label)

    def add(self, text, action):
        self.content.addWidget(self.button(text, action))

    def row(self, actions):
        row = QHBoxLayout()
        for text, action, enabled in actions:
            b = self.button(text, action)
            b.setEnabled(enabled)
            row.addWidget(b)
        self.content.addLayout(row)

    def clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear(item.layout())

    def render(self):
        self.clear(self.content)
        if self.error:
            self.label(self.error)
            self.add('Reintentar', self.retry)
        elif self.status is None:
            self.label('Conectando con el servicio de respaldo…')
        else:
            self.mode.setText('DEMO · no copia archivos' if self.status['demo'] else 'MOTOR REAL')
            if self.tab == 'Estado' or (self.tab == 'Copiar' and
                    (self.status['job']['state'] == 'running' or self.step == 3)):
                self.job_view()
            elif self.tab == 'Copiar':
                self.copy_view()
            elif self.tab == 'Archivos':
                self.files_view()
            else:
                self.settings_view()
        self.content.addStretch()

    def retry(self):
        self.error = ''
        self.refresh()
        if self.tab == 'Archivos':
            self.load_files()
        self.render()

    def job_view(self):
        job = self.status['job']
        self.label(job['message'])
        if job['state'] == 'running':
            bar = QProgressBar()
            if job['progress'] is None:
                bar.setRange(0, 0)
            else:
                bar.setValue(job['progress'])
            self.content.addWidget(bar)
        else:
            self.add('Nuevo respaldo', self.new_job)

    def new_job(self):
        self.tab, self.step, self.page = 'Copiar', 0, 0
        self.source = self.destination = None
        self.render()

    def choose(self, device):
        if self.step == 0:
            self.source = device
        else:
            self.destination = device
        self.step += 1
        self.page = 0
        self.render()

    def copy_view(self):
        self.label(('1 · Elegir origen', '2 · Elegir destino', '3 · Confirmar')[self.step])
        if self.step < 2:
            group = 'sources' if self.step == 0 else 'destinations'
            devices = [d for d in self.devices[group]
                       if self.step == 0 or d['id'] != self.source['id']]
            pages = max(1, (len(devices) + 1) // 2)
            self.page = min(self.page, pages - 1)
            for device in devices[self.page * 2:self.page * 2 + 2]:
                self.add(device['label'], lambda d=device: self.choose(d))
            if not devices:
                self.label('No hay perfiles disponibles.')
            self.row([
                ('Volver', lambda: self.back_step(), self.step > 0),
                ('Anterior', lambda: self.change_page(-1), self.page > 0),
                ('Siguiente', lambda: self.change_page(1), self.page < pages - 1),
            ])
        else:
            self.label('De: ' + self.source['label'] + '\nA: ' + self.destination['label'])
            self.label('No se copiarán archivos.' if self.status['demo'] else 'Copiar sin borrar el origen.')
            self.row([
                ('Volver', self.back_step, not self.pending),
                ('Simular' if self.status['demo'] else 'Iniciar copia', self.start_job, not self.pending),
            ])

    def back_step(self):
        self.step = max(0, self.step - 1)
        self.page = 0
        self.render()

    def change_page(self, delta):
        self.page += delta
        if self.tab == 'Archivos':
            self.load_files()
        else:
            self.render()

    def start_job(self):
        if self.pending:
            return
        self.pending = True
        self.render()

        def done(data):
            self.pending = False
            self.status, self.step = data, 3
            self.render()
        self.request('/api/backup', done,
                     {'source': self.source['id'], 'destination': self.destination['id']},
                     failure=lambda: setattr(self, 'pending', False))

    def load_files(self):
        self.file_request += 1
        generation = self.file_request
        self.files_loading = True
        self.render()

        def done(data):
            if generation == self.file_request:
                self.files_loading = False
                self.files, self.page = data, data['page']
                self.render()
        self.request('/api/files?' + urlencode({'path': self.path, 'page': self.page}), done,
                     failure=lambda: setattr(self, 'files_loading', False))

    def open_entry(self, entry):
        if entry['directory']:
            self.path = '/'.join(filter(None, (self.path, entry['name'])))
            self.page = 0
            self.load_files()
        else:
            self.detail = entry
            self.render()

    def up(self):
        self.path = self.path.rpartition('/')[0]
        self.page = 0
        self.load_files()

    def files_view(self):
        if self.files_loading:
            self.label('Leyendo carpeta…')
            return
        if self.detail:
            self.label(self.detail['name'])
            self.label(f"Tamaño: {self.detail['size'] / 1000000:.1f} MB · solo lectura")
            self.add('Volver', lambda: self.switch('Archivos'))
            return
        self.label(QFontMetrics(self.font()).elidedText(
            self.path or 'Archivos del respaldo', Qt.TextElideMode.ElideMiddle, 450))
        for entry in self.files['entries']:
            self.add(('▸ ' if entry['directory'] else '') + entry['name'],
                     lambda e=entry: self.open_entry(e))
        if not self.files['entries']:
            self.label('Carpeta vacía')
        self.row([
            ('Subir', self.up, bool(self.path)),
            ('Anterior', lambda: self.change_page(-1), self.page > 0),
            ('Siguiente', lambda: self.change_page(1), self.page < self.files['pages'] - 1),
        ])

    def settings_view(self):
        self.label(self.setting or 'Ajustes')
        if not self.setting:
            for name in ('Copia', 'Pantalla', 'Sistema'):
                self.add(name, lambda n=name: self.show_setting(n))
        else:
            if self.setting == 'Copia':
                self.label('Checksum · se aplica al próximo respaldo')
                self.add('Activado' if self.status['checksum'] else 'Desactivado', self.toggle_checksum)
            elif self.setting == 'Pantalla':
                self.label('480 × 320 · pantalla SPI\nInterfaz nativa Qt · sin escritorio')
            else:
                self.label('DEMO' if self.status['demo'] else 'Little Backup Box · motor CLI')
                self.label('Ajustes de copia: solo esta sesión')
            self.add('Volver', lambda: self.show_setting(None))

    def show_setting(self, name):
        self.setting = name
        self.render()

    def toggle_checksum(self):
        def done(data):
            self.status = data
            self.render()
        self.request('/api/settings', done, {'checksum': not self.status['checksum']})


def main():
    parser = argparse.ArgumentParser(description='Pantalla táctil nativa de Little Backup Box')
    parser.add_argument('--windowed', action='store_true', help='Previsualizar en un escritorio')
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    screen = Screen()
    if args.windowed:
        screen.show()
    else:
        screen.setCursor(Qt.CursorShape.BlankCursor)
        screen.showFullScreen()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
