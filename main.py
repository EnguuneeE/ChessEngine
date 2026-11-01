"""Entry point: play in the terminal or speak UCI to a chess GUI."""

import sys

from chess_engine.board import BLACK, WHITE
from chess_engine.cli import play
from chess_engine.uci import UCI


def main(argv) -> int:
    mode = argv[1].lower() if len(argv) > 1 else "play"

    if mode == "gui":
        from gui import run_gui as gui
        gui()
        return 0

    if mode == "uci":
        UCI().run()
        return 0

    if mode == "play":
        color = WHITE
        movetime = 1.5
        for arg in argv[2:]:
            lowered = arg.lower()
            if lowered in ("black", "b"):
                color = BLACK
            elif lowered in ("white", "w"):
                color = WHITE
            else:
                try:
                    movetime = float(arg)
                except ValueError:
                    print(f"Unknown argument: {arg}")
                    return 1
        play(color, movetime)
        return 0

    print("Usage:")
    print("  python main.py                 play as White")
    print("  python main.py gui             open the graphical board")
    print("  python main.py play 2.0        think for 2 seconds per move")
    print("  python main.py uci             UCI mode (for chess GUIs)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
