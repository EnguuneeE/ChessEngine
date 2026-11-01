"""SAN move notation for display and human input."""

from __future__ import annotations

from .board import (
    BISHOP,
    EMPTY,
    FILES,
    FLAG_CAPTURE,
    FLAG_CASTLE,
    FLAG_EP,
    FLAG_PROMO_CAPTURE,
    KING,
    KNIGHT,
    PAWN,
    QUEEN,
    RANKS,
    ROOK,
    color_of,
    move_uci,
    square_name,
    type_of,
)
from .movegen import legal_moves

PIECE_LETTERS = {
    KNIGHT: "N",
    BISHOP: "B",
    ROOK: "R",
    QUEEN: "Q",
    KING: "K",
}


def move_to_san(board, move: tuple) -> str:
    frm, to, promo, flag = move

    if flag == FLAG_CASTLE:
        san = "O-O" if (to & 7) == 6 else "O-O-O"
    else:
        piece = board.squares[frm]
        ptype = type_of(piece)
        capture = (flag in (FLAG_CAPTURE, FLAG_EP, FLAG_PROMO_CAPTURE)
                   or board.squares[to] != EMPTY)

        if ptype == PAWN:
            san = ""
            if capture:
                san += FILES[frm & 7] + "x"
            san += square_name(to)
            if promo:
                san += "=" + PIECE_LETTERS[promo]
        else:
            san = PIECE_LETTERS[ptype]

            others = []
            for candidate in legal_moves(board):
                if candidate == move or candidate[1] != to or candidate[2]:
                    continue
                other_piece = board.squares[candidate[0]]
                if (type_of(other_piece) == ptype
                        and color_of(other_piece) == color_of(piece)):
                    others.append(candidate)

            if others:
                same_file = any((m[0] & 7) == (frm & 7) for m in others)
                same_rank = any((m[0] >> 3) == (frm >> 3) for m in others)
                if not same_file:
                    san += FILES[frm & 7]
                elif not same_rank:
                    san += RANKS[frm >> 3]
                else:
                    san += square_name(frm)

            if capture:
                san += "x"
            san += square_name(to)

    board.make_move(move)
    if board.is_in_check():
        if not legal_moves(board):
            san += "#"
        else:
            san += "+"
    board.unmake_move(move)
    return san


def parse_move_input(board, text: str, moves=None):
    if moves is None:
        moves = legal_moves(board)
    text = text.strip()
    if not text:
        return None

    lowered = text.lower()
    for move in moves:
        if move_uci(move) == lowered:
            return move

    normalized = text.replace("0", "O").replace("+", "").replace("#", "").strip()
    for move in moves:
        san = move_to_san(board, move).replace("+", "").replace("#", "").strip()
        if san == normalized or san.lower() == normalized.lower():
            return move
    return None
