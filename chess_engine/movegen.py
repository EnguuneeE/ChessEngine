"""Pseudo-legal and legal move generation."""

from __future__ import annotations

from .board import (
    BLACK,
    BISHOP,
    CASTLE_BK,
    CASTLE_BQ,
    CASTLE_WK,
    CASTLE_WQ,
    EMPTY,
    FLAG_CAPTURE,
    FLAG_CASTLE,
    FLAG_DOUBLE,
    FLAG_EP,
    FLAG_NORMAL,
    FLAG_PROMO,
    FLAG_PROMO_CAPTURE,
    KING,
    KNIGHT,
    KNIGHT_DELTAS,
    KING_DELTAS,
    BISHOP_DIRS,
    ROOK_DIRS,
    PAWN,
    QUEEN,
    ROOK,
    WHITE,
    color_of,
    make_piece,
    move_uci,
    type_of,
)

PROMOTION_PIECES = (QUEEN, ROOK, BISHOP, KNIGHT)
TACTICAL_FLAGS = (FLAG_CAPTURE, FLAG_EP, FLAG_PROMO, FLAG_PROMO_CAPTURE)


def _add_pawn_moves(board, frm: int, color: int, moves: list,
                    captures_only: bool = False) -> None:
    squares = board.squares
    f, r = frm & 7, frm >> 3
    direction = 8 if color == WHITE else -8
    start_rank = 1 if color == WHITE else 6
    promo_rank = 7 if color == WHITE else 0

    to = frm + direction
    if 0 <= to < 64 and squares[to] == EMPTY:
        if (to >> 3) == promo_rank:
            for promo in PROMOTION_PIECES:
                moves.append((frm, to, promo, FLAG_PROMO))
        elif not captures_only:
            moves.append((frm, to, 0, FLAG_NORMAL))
            if r == start_rank:
                to2 = frm + 2 * direction
                if squares[to2] == EMPTY:
                    moves.append((frm, to2, 0, FLAG_DOUBLE))

    capture_rank = r + (1 if color == WHITE else -1)
    if 0 <= capture_rank < 8:
        base = capture_rank * 8
        for df in (-1, 1):
            nf = f + df
            if not 0 <= nf < 8:
                continue
            to = base + nf
            target = squares[to]
            if target != EMPTY and color_of(target) != color:
                if capture_rank == promo_rank:
                    for promo in PROMOTION_PIECES:
                        moves.append((frm, to, promo, FLAG_PROMO_CAPTURE))
                else:
                    moves.append((frm, to, 0, FLAG_CAPTURE))
            elif board.ep != -1 and to == board.ep:
                moves.append((frm, to, 0, FLAG_EP))


def _add_step_moves(board, frm: int, color: int, deltas, moves: list,
                    captures_only: bool = False) -> None:
    squares = board.squares
    f, r = frm & 7, frm >> 3
    for df, dr in deltas:
        nf, nr = f + df, r + dr
        if 0 <= nf < 8 and 0 <= nr < 8:
            to = nr * 8 + nf
            target = squares[to]
            if target == EMPTY:
                if not captures_only:
                    moves.append((frm, to, 0, FLAG_NORMAL))
            elif color_of(target) != color:
                moves.append((frm, to, 0, FLAG_CAPTURE))


def _add_sliding_moves(board, frm: int, color: int, dirs, moves: list,
                       captures_only: bool = False) -> None:
    squares = board.squares
    f, r = frm & 7, frm >> 3
    for df, dr in dirs:
        nf, nr = f + df, r + dr
        while 0 <= nf < 8 and 0 <= nr < 8:
            to = nr * 8 + nf
            target = squares[to]
            if target == EMPTY:
                if not captures_only:
                    moves.append((frm, to, 0, FLAG_NORMAL))
            else:
                if color_of(target) != color:
                    moves.append((frm, to, 0, FLAG_CAPTURE))
                break
            nf += df
            nr += dr


def _add_castling_moves(board, color: int, moves: list,
                        captures_only: bool = False) -> None:
    if captures_only:
        return
    squares = board.squares
    if color == WHITE:
        king = board.king_sq[WHITE]
        if king != 4:
            return
        if (board.castling & CASTLE_WK
                and squares[7] == make_piece(WHITE, ROOK)
                and squares[5] == EMPTY
                and squares[6] == EMPTY
                and not board.is_square_attacked(4, BLACK)
                and not board.is_square_attacked(5, BLACK)
                and not board.is_square_attacked(6, BLACK)):
            moves.append((4, 6, 0, FLAG_CASTLE))
        if (board.castling & CASTLE_WQ
                and squares[0] == make_piece(WHITE, ROOK)
                and squares[1] == EMPTY
                and squares[2] == EMPTY
                and squares[3] == EMPTY
                and not board.is_square_attacked(4, BLACK)
                and not board.is_square_attacked(3, BLACK)
                and not board.is_square_attacked(2, BLACK)):
            moves.append((4, 2, 0, FLAG_CASTLE))
    else:
        king = board.king_sq[BLACK]
        if king != 60:
            return
        if (board.castling & CASTLE_BK
                and squares[63] == make_piece(BLACK, ROOK)
                and squares[61] == EMPTY
                and squares[62] == EMPTY
                and not board.is_square_attacked(60, WHITE)
                and not board.is_square_attacked(61, WHITE)
                and not board.is_square_attacked(62, WHITE)):
            moves.append((60, 62, 0, FLAG_CASTLE))
        if (board.castling & CASTLE_BQ
                and squares[56] == make_piece(BLACK, ROOK)
                and squares[57] == EMPTY
                and squares[58] == EMPTY
                and squares[59] == EMPTY
                and not board.is_square_attacked(60, WHITE)
                and not board.is_square_attacked(59, WHITE)
                and not board.is_square_attacked(58, WHITE)):
            moves.append((60, 58, 0, FLAG_CASTLE))


def _generate(board, captures_only: bool) -> list:
    moves = []
    squares = board.squares
    turn = board.turn

    for frm in range(64):
        piece = squares[frm]
        if piece == EMPTY or color_of(piece) != turn:
            continue
        ptype = type_of(piece)
        if ptype == PAWN:
            _add_pawn_moves(board, frm, turn, moves, captures_only)
        elif ptype == KNIGHT:
            _add_step_moves(board, frm, turn, KNIGHT_DELTAS, moves,
                            captures_only)
        elif ptype == BISHOP:
            _add_sliding_moves(board, frm, turn, BISHOP_DIRS, moves,
                               captures_only)
        elif ptype == ROOK:
            _add_sliding_moves(board, frm, turn, ROOK_DIRS, moves,
                               captures_only)
        elif ptype == QUEEN:
            _add_sliding_moves(board, frm, turn, BISHOP_DIRS, moves,
                               captures_only)
            _add_sliding_moves(board, frm, turn, ROOK_DIRS, moves,
                               captures_only)
        elif ptype == KING:
            _add_step_moves(board, frm, turn, KING_DELTAS, moves,
                            captures_only)

    _add_castling_moves(board, turn, moves, captures_only)
    return moves


def generate_pseudo_moves(board) -> list:
    return _generate(board, False)


def generate_tactical_moves(board) -> list:
    return _generate(board, True)


def _legal_from_pseudo(board, pseudo_moves) -> list:
    moves = []
    for move in pseudo_moves:
        board.make_move(move)
        if not board.is_square_attacked(board.king_sq[board.turn ^ 1], board.turn):
            moves.append(move)
        board.unmake_move(move)
    return moves


def legal_moves(board) -> list:
    return _legal_from_pseudo(board, generate_pseudo_moves(board))


def tactical_moves(board) -> list:
    return _legal_from_pseudo(board, generate_tactical_moves(board))


def perft(board, depth: int) -> int:
    if depth == 0:
        return 1
    moves = legal_moves(board)
    if depth == 1:
        return len(moves)
    total = 0
    for move in moves:
        board.make_move(move)
        total += perft(board, depth - 1)
        board.unmake_move(move)
    return total


def parse_uci_move(board, text: str):
    text = text.strip().lower()
    moves = legal_moves(board)
    for move in moves:
        if move_uci(move) == text:
            return move
    castling_aliases = {
        "e1h1": (4, 6),
        "e1a1": (4, 2),
        "e8h8": (60, 62),
        "e8a8": (60, 58),
    }
    alias = castling_aliases.get(text)
    if alias:
        for move in moves:
            if move[3] == FLAG_CASTLE and (move[0], move[1]) == alias:
                return move
    return None
