"""Alpha-beta search with iterative deepening, quiescence and a transposition table."""

from __future__ import annotations

import time

from .board import (
    FLAG_CAPTURE,
    FLAG_EP,
    FLAG_PROMO_CAPTURE,
    PAWN,
    type_of,
)
from .eval import evaluate
from .movegen import legal_moves, tactical_moves

INF = 1_000_000
MATE = 100_000
MATE_THRESHOLD = MATE - 1000
MAX_PLY = 128
QSEARCH_MAX_PLY = 32
QSEARCH_DEPTH = 8
DELTA_MARGIN = 200

TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2

ORDER_VALUES = {PAWN: 100, 2: 320, 3: 330, 4: 500, 5: 900, 6: 20000}


class SearchAborted(Exception):
    pass


class Searcher:
    def __init__(self, board, tt_capacity: int = 250_000):
        self.board = board
        self.tt = {}
        self.tt_capacity = tt_capacity
        self.nodes = 0
        self.start_time = 0.0
        self.time_limit = None
        self.node_limit = None
        self.stop_flag = False
        self.killers = [[None, None] for _ in range(MAX_PLY)]
        self.history = [[0] * 64 for _ in range(64)]
        self.pv_table = [[None] * MAX_PLY for _ in range(MAX_PLY)]
        self.pv_length = [0] * MAX_PLY
        self.partial_root_best = None

    def clear(self) -> None:
        self.tt.clear()
        self.killers = [[None, None] for _ in range(MAX_PLY)]
        self.history = [[0] * 64 for _ in range(64)]
        self.partial_root_best = None

    # ------------------------------------------------------------------ time

    def _check_limits(self) -> None:
        if self.stop_flag:
            raise SearchAborted
        if self.node_limit is not None and self.nodes >= self.node_limit:
            raise SearchAborted
        if (self.time_limit is not None
                and time.monotonic() - self.start_time >= self.time_limit):
            raise SearchAborted

    # -------------------------------------------------------- move ordering

    def _score_move(self, move: tuple, tt_move, ply: int) -> int:
        if move == tt_move:
            return 10_000_000
        frm, to, promo, flag = move
        squares = self.board.squares

        if promo:
            if flag == FLAG_PROMO_CAPTURE:
                victim = ORDER_VALUES[type_of(squares[to])]
                return 8_000_000 + ORDER_VALUES[promo] * 10 + victim
            return 8_000_000 + ORDER_VALUES[promo]

        if flag == FLAG_CAPTURE or flag == FLAG_EP:
            victim = PAWN if flag == FLAG_EP else type_of(squares[to])
            attacker = type_of(squares[frm])
            return 7_000_000 + ORDER_VALUES[victim] * 10 - ORDER_VALUES[attacker]

        if self.killers[ply][0] == move:
            return 6_000_000
        if self.killers[ply][1] == move:
            return 5_999_999
        return self.history[frm][to]

    def _order_moves(self, moves: list, tt_move, ply: int) -> None:
        moves.sort(key=lambda m: self._score_move(m, tt_move, ply), reverse=True)

    # ------------------------------------------------------------- quiescence

    def quiescence(self, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if (self.nodes & 1023) == 0:
            self._check_limits()

        board = self.board
        self.pv_length[ply] = ply

        if ply >= QSEARCH_MAX_PLY:
            return evaluate(board)

        if ply > 0 and (board.halfmove >= 100 or board.is_repetition(1)):
            return 0

        in_check = board.is_in_check()
        if not in_check:
            stand_pat = evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            if stand_pat > alpha:
                alpha = stand_pat
            moves = tactical_moves(board)
        else:
            moves = legal_moves(board)

        if not moves:
            if in_check:
                return -MATE + ply
            return alpha

        self._order_moves(moves, None, ply)

        for move in moves:
            board.make_move(move)
            try:
                score = -self.quiescence(-beta, -alpha, ply + 1)
            finally:
                board.unmake_move(move)
            if score > alpha:
                alpha = score
                if alpha >= beta:
                    break
        return alpha

    # --------------------------------------------------------------- negamax

    def negamax(self, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if (self.nodes & 1023) == 0:
            self._check_limits()

        board = self.board
        self.pv_length[ply] = ply

        if ply >= MAX_PLY - 1:
            return evaluate(board)

        if ply > 0 and (board.halfmove >= 100 or board.is_repetition(1)):
            return 0

        in_check = board.is_in_check()
        if in_check:
            depth += 1

        if depth <= 0:
            return self.quiescence(alpha, beta, ply)

        if alpha < -MATE + ply:
            alpha = -MATE + ply
        if beta > MATE - ply - 1:
            beta = MATE - ply - 1
        if alpha >= beta:
            return alpha

        alpha_orig = alpha
        tt_move = None
        entry = self.tt.get(board.hash)
        if entry is not None:
            tt_depth, tt_score, tt_flag, tt_move = entry
            if ply > 0 and tt_depth >= depth:
                if tt_score >= MATE_THRESHOLD:
                    tt_score -= ply
                elif tt_score <= -MATE_THRESHOLD:
                    tt_score += ply
                if tt_flag == TT_EXACT:
                    return tt_score
                if tt_flag == TT_LOWER and tt_score >= beta:
                    return tt_score
                if tt_flag == TT_UPPER and tt_score <= alpha:
                    return tt_score

        moves = legal_moves(board)
        if not moves:
            if in_check:
                return -MATE + ply
            return 0

        self._order_moves(moves, tt_move, ply)

        best_score = -INF
        best_move = None
        for move in moves:
            board.make_move(move)
            try:
                score = -self.negamax(depth - 1, -beta, -alpha, ply + 1)
            finally:
                board.unmake_move(move)

            if score > best_score:
                best_score = score
                best_move = move
                if ply == 0:
                    self.partial_root_best = move
                if score > alpha:
                    alpha = score
                    self.pv_table[ply][ply] = move
                    for j in range(ply + 1, self.pv_length[ply + 1]):
                        self.pv_table[ply][j] = self.pv_table[ply + 1][j]
                    self.pv_length[ply] = self.pv_length[ply + 1]

            if alpha >= beta:
                if not (move[2] or move[3] in
                        (FLAG_CAPTURE, FLAG_EP, FLAG_PROMO_CAPTURE)):
                    self.killers[ply][1] = self.killers[ply][0]
                    self.killers[ply][0] = move
                    self.history[move[0]][move[1]] += depth * depth
                    if self.history[move[0]][move[1]] > 100_000:
                        for a in range(64):
                            for b in range(64):
                                self.history[a][b] //= 2
                break

        if best_score >= MATE_THRESHOLD:
            stored_score = best_score + ply
        elif best_score <= -MATE_THRESHOLD:
            stored_score = best_score - ply
        else:
            stored_score = best_score

        if best_score <= alpha_orig:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER
        else:
            flag = TT_EXACT

        if len(self.tt) >= self.tt_capacity:
            self.tt.clear()
        self.tt[board.hash] = (depth, stored_score, flag, best_move)

        return best_score

    # ----------------------------------------------------------------- search

    def search(self, time_limit=None, max_depth: int = 64,
               info_callback=None, node_limit=None):
        self.stop_flag = False
        self.nodes = 0
        self.time_limit = time_limit
        self.node_limit = node_limit
        self.start_time = time.monotonic()
        self.partial_root_best = None

        if not legal_moves(self.board):
            score = -MATE if self.board.is_in_check() else 0
            return None, score, 0

        best_move = None
        best_score = 0
        completed_depth = 0

        for depth in range(1, max_depth + 1):
            self.partial_root_best = None
            self.pv_table[0][0] = None
            try:
                score = self.negamax(depth, -INF, INF, 0)
            except SearchAborted:
                break

            move = self.pv_table[0][0]
            if move is None:
                move = self.partial_root_best
            if move is not None:
                best_move = move
                best_score = score
                completed_depth = depth

            if info_callback is not None:
                elapsed = max(time.monotonic() - self.start_time, 1e-6)
                info_callback(depth, score, self.pv_line(),
                              self.nodes, elapsed)

            if abs(score) >= MATE_THRESHOLD:
                break
            if (self.time_limit is not None
                    and time.monotonic() - self.start_time >= self.time_limit * 0.7):
                break

        if best_move is None:
            best_move = self.partial_root_best
        if best_move is None:
            moves = legal_moves(self.board)
            best_move = moves[0] if moves else None

        return best_move, best_score, completed_depth

    def pv_line(self) -> list:
        return [self.pv_table[0][i]
                for i in range(self.pv_length[0])
                if self.pv_table[0][i] is not None]
