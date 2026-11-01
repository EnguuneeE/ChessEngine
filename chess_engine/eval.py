"""Static evaluation: material, piece-square tables and pawn structure."""

from __future__ import annotations

from .board import (
    BISHOP,
    BLACK,
    KING,
    KNIGHT,
    PAWN,
    QUEEN,
    ROOK,
    WHITE,
)

PIECE_VALUES = {
    PAWN: 100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK: 500,
    QUEEN: 900,
    KING: 0,
}

PHASE_WEIGHTS = {KNIGHT: 1, BISHOP: 1, ROOK: 2, QUEEN: 4}
MAX_PHASE = 24

PAWN_PST = (
      0,   0,   0,   0,   0,   0,   0,   0,
     50,  50,  50,  50,  50,  50,  50,  50,
     10,  10,  20,  30,  30,  20,  10,  10,
      5,   5,  10,  25,  25,  10,   5,   5,
      0,   0,   0,  20,  20,   0,   0,   0,
      5,  -5, -10,   0,   0, -10,  -5,   5,
      5,  10,  10, -20, -20,  10,  10,   5,
      0,   0,   0,   0,   0,   0,   0,   0,
)

KNIGHT_PST = (
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
)

BISHOP_PST = (
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
)

ROOK_PST = (
      0,   0,   0,   0,   0,   0,   0,   0,
      5,  10,  10,  10,  10,  10,  10,   5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      0,   0,   0,   5,   5,   0,   0,   0,
)

QUEEN_PST = (
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
      0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20,
)

KING_MG_PST = (
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
     20,  20,   0,   0,   0,   0,  20,  20,
     20,  30,  10,   0,   0,  10,  30,  20,
)

KING_EG_PST = (
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10,   0,   0, -10, -20, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -30,   0,   0,   0,   0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50,
)

PST = {
    PAWN: PAWN_PST,
    KNIGHT: KNIGHT_PST,
    BISHOP: BISHOP_PST,
    ROOK: ROOK_PST,
    QUEEN: QUEEN_PST,
}

PASSED_BONUS = (0, 10, 20, 35, 60, 100, 160, 0)
BISHOP_PAIR_BONUS = 30
DOUBLED_PENALTY = 12
ISOLATED_PENALTY = 12
ROOK_OPEN_BONUS = 15
ROOK_SEMI_OPEN_BONUS = 8
TEMPO = 10


def evaluate(board) -> int:
    squares = board.squares
    score = 0
    phase = 0
    bishop_count = [0, 0]
    pawn_files = [[0] * 8, [0] * 8]
    pawns = [[], []]
    rook_files = [[], []]
    king_idx = [None, None]
    mating_material = [False, False]
    minors = []

    for sq, piece in enumerate(squares):
        if not piece:
            continue
        color = piece >> 3
        ptype = piece & 7
        idx = sq ^ 56 if color == WHITE else sq

        if ptype == KING:
            king_idx[color] = idx
            continue

        if ptype in (PAWN, ROOK, QUEEN):
            mating_material[color] = True
        elif ptype in (KNIGHT, BISHOP):
            minors.append((ptype, (sq & 7) ^ (sq >> 3)))

        value = PIECE_VALUES[ptype] + PST[ptype][idx]
        if color == WHITE:
            score += value
        else:
            score -= value

        if ptype == BISHOP:
            bishop_count[color] += 1
        elif ptype == PAWN:
            pawn_files[color][sq & 7] += 1
            pawns[color].append((sq & 7, sq >> 3))
        elif ptype == ROOK:
            rook_files[color].append(sq & 7)

        if ptype in PHASE_WEIGHTS:
            phase += PHASE_WEIGHTS[ptype]

    if not mating_material[WHITE] and not mating_material[BLACK]:
        if len(minors) <= 1:
            return 0
        if (len(minors) == 2
                and minors[0][0] == BISHOP
                and minors[1][0] == BISHOP
                and minors[0][1] == minors[1][1]):
            return 0

    phase = min(phase, MAX_PHASE)
    for color in (WHITE, BLACK):
        idx = king_idx[color]
        if idx is None:
            continue
        king_value = (KING_MG_PST[idx] * phase
                      + KING_EG_PST[idx] * (MAX_PHASE - phase)) // MAX_PHASE
        if color == WHITE:
            score += king_value
        else:
            score -= king_value

    if bishop_count[WHITE] >= 2:
        score += BISHOP_PAIR_BONUS
    if bishop_count[BLACK] >= 2:
        score -= BISHOP_PAIR_BONUS

    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        enemy = color ^ 1

        for f in range(8):
            count = pawn_files[color][f]
            if count > 1:
                score -= sign * DOUBLED_PENALTY * (count - 1)

        for f in range(8):
            if (pawn_files[color][f]
                    and not (f > 0 and pawn_files[color][f - 1])
                    and not (f < 7 and pawn_files[color][f + 1])):
                score -= sign * ISOLATED_PENALTY

        for f, r in pawns[color]:
            passed = True
            for ef, er in pawns[enemy]:
                if abs(ef - f) <= 1:
                    if color == WHITE and er > r:
                        passed = False
                        break
                    if color == BLACK and er < r:
                        passed = False
                        break
            if passed:
                bonus = PASSED_BONUS[r] if color == WHITE else PASSED_BONUS[7 - r]
                score += sign * bonus

        for f in rook_files[color]:
            if pawn_files[color][f] == 0:
                if pawn_files[enemy][f] == 0:
                    score += sign * ROOK_OPEN_BONUS
                else:
                    score += sign * ROOK_SEMI_OPEN_BONUS

    score += TEMPO if board.turn == WHITE else -TEMPO
    return score if board.turn == WHITE else -score
