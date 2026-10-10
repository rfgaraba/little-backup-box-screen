"""Hide the Linux console cursor before drawing the native interface."""
from pathlib import Path


def main():
    # The framebuffer console cursor is independent of Qt's mouse cursor.
    try:
        Path('/sys/class/graphics/fbcon/cursor_blink').write_text('0\n')
    except OSError:
        pass
    try:
        with Path('/dev/tty1').open('wb', buffering=0) as terminal:
            terminal.write(b'\x1b[?25l')
    except OSError:
        pass


if __name__ == '__main__':
    main()
