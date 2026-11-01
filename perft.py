"""Move generation validation with perft.

Run `python perft.py` for a quick suite, or `python perft.py 4` for deeper
checks (slower).
"""

import sys
import time

from chess_engine.board import Board
from chess_engine.movegen import perft

TESTS = [
    (
        "startpos",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        [20, 400, 8902, 197281, 4865609],
    ),
    (
        "kiwipete",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        [48, 2039, 97862, 4085603],
    ),
    (
        "position 3",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        [14, 191, 2812, 43238, 674624],
    ),
    (
        "position 4",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        [6, 264, 9467, 422333],
    ),
    (
        "position 5",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        [44, 1486, 62379, 2103487],
    ),
    (
        "position 6",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        [46, 2079, 89890, 3894594],
    ),
]


def main() -> int:
    max_depth = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    failures = 0

    for name, fen, expected in TESTS:
        board = Board(fen)
        depth_limit = min(max_depth, len(expected))
        for depth in range(1, depth_limit + 1):
            start = time.perf_counter()
            nodes = perft(board, depth)
            elapsed = time.perf_counter() - start
            want = expected[depth - 1]
            status = "ok" if nodes == want else "FAIL"
            if nodes != want:
                failures += 1
            nps = int(nodes / elapsed) if elapsed > 0 else 0
            print(f"{name:12s} depth {depth}: {nodes:>9d} "
                  f"(expected {want:>9d}) {status}  {elapsed:6.2f}s {nps} nps")

    if failures:
        print(f"\n{failures} perft check(s) failed.")
        return 1
    print("\nAll perft checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
