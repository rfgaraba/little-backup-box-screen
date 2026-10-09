"""Read-only display/input diagnostics; run on the Raspberry Pi over SSH."""
from pathlib import Path
import platform


def main():
    print('Sistema:', platform.platform())
    release = Path('/etc/os-release')
    if release.exists():
        print(release.read_text())
    print('Framebuffers (elegir el que corresponda al LCD SPI):')
    frames = sorted(Path('/sys/class/graphics').glob('fb[0-9]*'))
    for frame in frames:
        print('/dev/' + frame.name)
        for name in ('name', 'virtual_size', 'bits_per_pixel'):
            file = frame / name
            if file.exists():
                print(' ', name + ':', file.read_text().strip())
    if not frames:
        print('No se encontraron framebuffers; LinuxFB aún no puede usar la pantalla.')
    print('\nDispositivos DRM:')
    print('\n'.join(str(p) for p in sorted(Path('/dev/dri').glob('*'))) or 'Ninguno')
    print('\nEntradas táctiles/teclados:')
    inputs = Path('/proc/bus/input/devices')
    print(inputs.read_text() if inputs.exists() else 'No disponible')
    print('\nRutas estables de entrada:')
    print('\n'.join(str(p) for p in sorted(Path('/dev/input/by-path').glob('*'))) or 'Ninguna')


if __name__ == '__main__':
    main()
