"""Reuse upstream's rclone configuration and backup.py for remote backups."""
import configparser
import json
import os
from pathlib import Path
import subprocess


def state_dir():
    return Path(os.environ.get('LBB_SCREEN_STATE_DIR', Path(__file__).parent / '.runtime'))


class RemoteBackup:
    def __init__(self, config):
        self.config = config
        self.settings = {'enabled': False, 'target': ''}
        if config:
            try:
                value = json.loads((state_dir() / 'remote.json').read_text(encoding='utf-8'))
                if isinstance(value.get('enabled'), bool) and isinstance(value.get('target'), str):
                    self.settings = {k: value[k] for k in self.settings}
            except (OSError, ValueError, AttributeError):
                pass

    def config_path(self):
        # Ask the installed engine: constants and media paths vary by version.
        script = ('import json,os,lib_setup; s=lib_setup.setup(); '
                  'print(json.dumps(os.path.join(s.get_val("const_MEDIA_DIR"), '
                  's.get_val("const_RCLONE_CONFIG_FILE"))))')
        try:
            result = subprocess.run([self.config.get('python', 'python3'), '-c', script],
                                    cwd=self.config['engine_dir'], capture_output=True,
                                    text=True, check=True, timeout=15)
            path = Path(json.loads(result.stdout.strip().splitlines()[-1]))
            if not path.is_absolute():
                raise ValueError()
            return path
        except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
            raise ValueError('No se pudo consultar la configuración de nube del motor') from exc

    @staticmethod
    def parse(text):
        parser = configparser.RawConfigParser(interpolation=None)
        try:
            parser.read_string(text)
            if parser.defaults() or not parser.sections():
                raise ValueError()
            for name in parser.sections():
                if any(c in name for c in ':[]/\\\n\r') or not name.strip() or not parser.get(name, 'type', fallback=''):
                    raise ValueError()
        except (configparser.Error, ValueError) as exc:
            raise ValueError('El archivo debe ser un rclone.conf válido, sin cifrar') from exc
        return parser

    def status(self):
        result = dict(self.settings, available=bool(self.config), targets=[])
        if not self.config:
            return dict(result, message='La nube no se configura en modo demo')
        try:
            path = self.config_path()
            result['config_path'] = str(path)
            if path.exists() and path.stat().st_size:
                parser = self.parse(path.read_text(encoding='utf-8'))
                result['targets'] = [{'id': 'cloud:' + name, 'label': name,
                                      'type': parser.get(name, 'type')} for name in parser.sections()]
            result['message'] = 'Elegí una cuenta para subir después del respaldo local'
        except (OSError, ValueError) as exc:
            result.update(available=False, message=str(exc) if isinstance(exc, ValueError) else 'No se pudo leer rclone.conf')
        return result

    def save(self, data):
        if not self.config:
            raise ValueError('La nube no se configura en modo demo')
        if not isinstance(data.get('enabled'), bool) or not isinstance(data.get('target'), str):
            raise ValueError('Configuración de nube inválida')
        if data['enabled'] and data['target'] not in [t['id'] for t in self.status()['targets']]:
            raise ValueError('Elegí una cuenta configurada en Little Backup Box')
        settings = {k: data[k] for k in self.settings}
        root = state_dir()
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / 'remote.json.tmp'
        temporary.write_text(json.dumps(settings), encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(root / 'remote.json')
        self.settings = settings

    def import_config(self, text):
        if not self.config or not isinstance(text, str) or len(text.encode('utf-8')) > 65536:
            raise ValueError('Archivo de nube inválido (máximo 64 KB)')
        incoming = self.parse(text)
        path = self.config_path()
        existing = self.parse(path.read_text(encoding='utf-8')) if path.exists() and path.stat().st_size else configparser.RawConfigParser()
        if set(existing.sections()) & set(incoming.sections()):
            raise ValueError('Ya existe una cuenta con ese nombre; usá otro nombre en rclone')
        for section in incoming.sections():
            existing[section] = dict(incoming[section])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.screen.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as output:
                temporary.chmod(0o600)
                existing.write(output)
            if os.name == 'posix':
                import pwd
                owner = path.stat() if path.exists() else pwd.getpwnam('www-data')
                os.chown(temporary, owner.st_uid if path.exists() else owner.pw_uid,
                         owner.st_gid if path.exists() else owner.pw_gid)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def command(self, source, checksum):
        if not self.settings['enabled']:
            return None
        if self.settings['target'] not in [t['id'] for t in self.status()['targets']]:
            raise ValueError('La cuenta de nube seleccionada ya no está disponible')
        from server import command
        return command(self.config, dict(source, id='remote-source'),
                       {'id': 'remote-target', 'engine': self.settings['target']}, checksum,
                       allow_cloud=True)
