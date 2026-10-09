"""Create a portable installer ZIP without development dependencies or settings."""
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from install import FILES


def build():
    output = ROOT / 'dist/little-backup-box-screen-installer.zip'
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as bundle:
        for name in (*FILES, 'install.py', 'install.sh'):
            bundle.write(ROOT / name, f'little-backup-box-screen/{name}')
    print(output)
    return output


if __name__ == '__main__':
    build()
