"""UCI protocol implementation."""

from __future__ import annotations

import sys
import threading

from .board import BLACK, START_FEN, WHITE, Board, move_uci
from .movegen import legal_moves, parse_uci_move
from .search import MATE, MATE_THRESHOLD, Searcher

GO_INT_KEYS = {
    "wtime", "btime", "winc", "binc", "movestogo",
    "depth", "movetime", "nodes",
}
GO_KEYWORDS = GO_INT_KEYS | {"infinite", "ponder", "searchmoves"}


def format_score(score: int) -> str:
    if score >= MATE_THRESHOLD:
        return f"mate {(MATE - score + 1) // 2}"
    if score <= -MATE_THRESHOLD:
        return f"mate {-((MATE + score + 1) // 2)}"
    return f"cp {score}"


class UCI:
    def __init__(self):
        self.board = Board()
        self.searcher = Searcher(self.board)
        self.thread = None
        self.stop_event = threading.Event()

    # --------------------------------------------------------------- main loop

    def run(self) -> None:
        try:
            for raw in sys.stdin:
                line = raw.strip()
                if not line:
                    continue
                if line == "quit":
                    break
                self._handle(line)
        finally:
            self._stop_search()
            if self.thread is not None:
                self.thread.join(timeout=2.0)

    def _handle(self, line: str) -> None:
        tokens = line.split()
        command = tokens[0]

        if command == "uci":
            print("id name PyChessEngine 1.0", flush=True)
            print("id author OpenCode", flush=True)
            print("uciok", flush=True)
        elif command == "isready":
            print("readyok", flush=True)
        elif command == "ucinewgame":
            self._stop_search()
            self._join_search()
            self.board.set_fen(START_FEN)
            self.searcher.clear()
        elif command == "position":
            self._stop_search()
            self._join_search()
            self._cmd_position(tokens)
        elif command == "go":
            self._start_search(tokens)
        elif command == "stop":
            self._stop_search()
        elif command == "d":
            print(self.board, flush=True)
            print("Fen:", self.board.fen(), flush=True)
        elif command in ("setoption", "ponderhit", "debug"):
            pass

    # ---------------------------------------------------------------- position

    def _cmd_position(self, tokens) -> None:
        if len(tokens) < 2:
            return

        if tokens[1] == "startpos":
            fen = START_FEN
            idx = 2
        elif tokens[1] == "fen":
            end = len(tokens)
            if "moves" in tokens:
                end = tokens.index("moves")
            fen = " ".join(tokens[2:end])
            idx = end
        else:
            return

        try:
            self.board.set_fen(fen)
        except (ValueError, KeyError):
            return

        if idx < len(tokens) and tokens[idx] == "moves":
            for token in tokens[idx + 1:]:
                move = parse_uci_move(self.board, token)
                if move is None:
                    break
                self.board.make_move(move)

    # ------------------------------------------------------------------- go

    def _parse_go(self, tokens) -> dict:
        params = {}
        i = 1
        while i < len(tokens):
            token = tokens[i]
            if token in GO_INT_KEYS and i + 1 < len(tokens):
                try:
                    params[token] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token in ("infinite", "ponder"):
                params[token] = True
                i += 1
            elif token == "searchmoves":
                i += 1
                while i < len(tokens) and tokens[i] not in GO_KEYWORDS:
                    i += 1
            else:
                i += 1

        if not params:
            params["infinite"] = True
        return params

    def _compute_time(self, params) -> float | None:
        if "movetime" in params:
            return max(0.005, params["movetime"] / 1000.0 - 0.02)
        if params.get("infinite"):
            return None

        turn = self.board.turn
        remaining = params.get("wtime" if turn == WHITE else "btime")
        if remaining is None:
            return None

        increment = params.get("winc" if turn == WHITE else "binc", 0)
        remaining /= 1000.0
        increment /= 1000.0
        movestogo = params.get("movestogo")

        if movestogo:
            allocation = remaining / max(1, movestogo) + increment * 0.5
        else:
            allocation = remaining / 30.0 + increment * 0.8

        allocation = min(allocation, remaining * 0.8)
        return max(0.005, allocation - 0.03)

    def _start_search(self, tokens) -> None:
        if self.thread is not None and self.thread.is_alive():
            self._stop_search()
            self._join_search()

        params = self._parse_go(tokens)
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._search_worker, args=(params,), daemon=True)
        self.thread.start()

    def _stop_search(self) -> None:
        self.searcher.stop_flag = True
        self.stop_event.set()

    def _join_search(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def _search_worker(self, params) -> None:
        try:
            time_limit = self._compute_time(params)
            max_depth = params.get("depth", 64)
            node_limit = params.get("nodes")
            infinite = params.get("infinite", False)

            def info(depth, score, pv, nodes, elapsed):
                nps = int(nodes / max(elapsed, 0.001))
                pv_text = " ".join(move_uci(m) for m in pv)
                print(
                    f"info depth {depth} score {format_score(score)} "
                    f"nodes {nodes} nps {nps} time {int(elapsed * 1000)} "
                    f"pv {pv_text}",
                    flush=True,
                )

            best, _score, _depth = self.searcher.search(
                time_limit=time_limit,
                max_depth=max_depth,
                info_callback=info,
                node_limit=node_limit,
            )

            if infinite and not self.stop_event.is_set():
                while not self.stop_event.wait(0.1):
                    pass

            if best is None:
                moves = legal_moves(self.board)
                best = moves[0] if moves else None

            if best is None:
                print("bestmove 0000", flush=True)
            else:
                print(f"bestmove {move_uci(best)}", flush=True)
        except Exception as exc:  # keep the engine alive
            print(f"info string error: {exc}", flush=True)
