"""Board representation, FEN handling, move making and attack detection."""

from __future__ import annotations

import random

WHITE, BLACK = 0, 1

EMPTY = 0
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

CASTLE_WK, CASTLE_WQ, CASTLE_BK, CASTLE_BQ = 1, 2, 4, 8
CASTLE_ALL = CASTLE_WK | CASTLE_WQ | CASTLE_BK | CASTLE_BQ

FLAG_NORMAL = 0
FLAG_CAPTURE = 1
FLAG_DOUBLE = 2
FLAG_EP = 3
FLAG_CASTLE = 4
FLAG_PROMO = 5
FLAG_PROMO_CAPTURE = 6

FILES = "abcdefgh"
RANKS = "12345678"


def make_piece(color: int, ptype: int) -> int:
    return ptype | (color << 3)


def color_of(piece: int) -> int:
    return piece >> 3


def type_of(piece: int) -> int:
    return piece & 7


def square_name(sq: int) -> str:
    return FILES[sq & 7] + RANKS[sq >> 3]


def parse_square(name: str) -> int:
    return (ord(name[1]) - 49) * 8 + (ord(name[0]) - 97)


PIECE_CHARS = {
    "P": make_piece(WHITE, PAWN),
    "N": make_piece(WHITE, KNIGHT),
    "B": make_piece(WHITE, BISHOP),
    "R": make_piece(WHITE, ROOK),
    "Q": make_piece(WHITE, QUEEN),
    "K": make_piece(WHITE, KING),
    "p": make_piece(BLACK, PAWN),
    "n": make_piece(BLACK, KNIGHT),
    "b": make_piece(BLACK, BISHOP),
    "r": make_piece(BLACK, ROOK),
    "q": make_piece(BLACK, QUEEN),
    "k": make_piece(BLACK, KING),
}
CHAR_BY_PIECE = {v: k for k, v in PIECE_CHARS.items()}

KNIGHT_DELTAS = ((-2, -1), (-2, 1), (-1, -2), (-1, 2),
                 (1, -2), (1, 2), (2, -1), (2, 1))
KING_DELTAS = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
               (0, 1), (1, -1), (1, 0), (1, 1))
BISHOP_DIRS = ((-1, -1), (-1, 1), (1, -1), (1, 1))
ROOK_DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))

_rng = random.Random(0x5EEDC0DE)
ZOBRIST_PIECE = [[_rng.getrandbits(64) for _ in range(64)] for _ in range(16)]
ZOBRIST_TURN = _rng.getrandbits(64)
ZOBRIST_CASTLING = [_rng.getrandbits(64) for _ in range(16)]
ZOBRIST_EP = [_rng.getrandbits(64) for _ in range(8)]

CASTLE_RIGHTS_MASK = [CASTLE_ALL] * 64
CASTLE_RIGHTS_MASK[4] = CASTLE_ALL & ~(CASTLE_WK | CASTLE_WQ)
CASTLE_RIGHTS_MASK[7] = CASTLE_ALL & ~CASTLE_WK
CASTLE_RIGHTS_MASK[0] = CASTLE_ALL & ~CASTLE_WQ
CASTLE_RIGHTS_MASK[60] = CASTLE_ALL & ~(CASTLE_BK | CASTLE_BQ)
CASTLE_RIGHTS_MASK[63] = CASTLE_ALL & ~CASTLE_BK
CASTLE_RIGHTS_MASK[56] = CASTLE_ALL & ~CASTLE_BQ


def move_uci(move: tuple) -> str:
    frm, to, promo, _flag = move
    text = square_name(frm) + square_name(to)
    if promo:
        text += "nbrq"[promo - KNIGHT]
    return text


class Board:
    __slots__ = (
        "squares",
        "turn",
        "castling",
        "ep",
        "halfmove",
        "fullmove",
        "king_sq",
        "hash",
        "undo_stack",
        "history_hashes",
    )

    def __init__(self, fen: str = START_FEN):
        self.squares = [EMPTY] * 64
        self.undo_stack = []
        self.history_hashes = []
        self.set_fen(fen)

    # ------------------------------------------------------------------ FEN

    def set_fen(self, fen: str) -> None:
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError("invalid FEN: need at least 4 fields")
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError("invalid FEN: board must have 8 ranks")

        squares = [EMPTY] * 64
        for ri, row in enumerate(rows):
            rank = 7 - ri
            file = 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                else:
                    squares[rank * 8 + file] = PIECE_CHARS[ch]
                    file += 1
            if file != 8:
                raise ValueError("invalid FEN: rank does not have 8 files")

        self.squares = squares
        self.turn = WHITE if parts[1] == "w" else BLACK

        castling = 0
        if "K" in parts[2]:
            castling |= CASTLE_WK
        if "Q" in parts[2]:
            castling |= CASTLE_WQ
        if "k" in parts[2]:
            castling |= CASTLE_BK
        if "q" in parts[2]:
            castling |= CASTLE_BQ
        self.castling = castling

        self.ep = -1 if parts[3] == "-" else parse_square(parts[3])
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1

        self.king_sq = [-1, -1]
        for sq, piece in enumerate(self.squares):
            if piece and type_of(piece) == KING:
                self.king_sq[color_of(piece)] = sq

        self.hash = self._compute_hash()
        self.undo_stack = []
        self.history_hashes = [self.hash]

    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row = ""
            empty = 0
            for file in range(8):
                piece = self.squares[rank * 8 + file]
                if piece == EMPTY:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += CHAR_BY_PIECE[piece]
            if empty:
                row += str(empty)
            rows.append(row)

        castling = ""
        if self.castling & CASTLE_WK:
            castling += "K"
        if self.castling & CASTLE_WQ:
            castling += "Q"
        if self.castling & CASTLE_BK:
            castling += "k"
        if self.castling & CASTLE_BQ:
            castling += "q"

        ep = square_name(self.ep) if self.ep != -1 else "-"
        side = "w" if self.turn == WHITE else "b"
        return (f"{'/'.join(rows)} {side} {castling or '-'} {ep} "
                f"{self.halfmove} {self.fullmove}")

    def _compute_hash(self) -> int:
        h = 0
        for sq, piece in enumerate(self.squares):
            if piece:
                h ^= ZOBRIST_PIECE[piece][sq]
        if self.turn == BLACK:
            h ^= ZOBRIST_TURN
        h ^= ZOBRIST_CASTLING[self.castling]
        if self.ep != -1:
            h ^= ZOBRIST_EP[self.ep & 7]
        return h

    # -------------------------------------------------------------- attacks

    def is_square_attacked(self, sq: int, by_color: int) -> bool:
        squares = self.squares
        f, r = sq & 7, sq >> 3

        pawn_rank = r - 1 if by_color == WHITE else r + 1
        if 0 <= pawn_rank < 8:
            pawn = make_piece(by_color, PAWN)
            base = pawn_rank * 8
            if f > 0 and squares[base + f - 1] == pawn:
                return True
            if f < 7 and squares[base + f + 1] == pawn:
                return True

        knight = make_piece(by_color, KNIGHT)
        for df, dr in KNIGHT_DELTAS:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                if squares[nr * 8 + nf] == knight:
                    return True

        king = make_piece(by_color, KING)
        for df, dr in KING_DELTAS:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                if squares[nr * 8 + nf] == king:
                    return True

        bishop = make_piece(by_color, BISHOP)
        queen = make_piece(by_color, QUEEN)
        rook = make_piece(by_color, ROOK)

        for df, dr in BISHOP_DIRS:
            nf, nr = f + df, r + dr
            while 0 <= nf < 8 and 0 <= nr < 8:
                target = squares[nr * 8 + nf]
                if target:
                    if target == bishop or target == queen:
                        return True
                    break
                nf += df
                nr += dr

        for df, dr in ROOK_DIRS:
            nf, nr = f + df, r + dr
            while 0 <= nf < 8 and 0 <= nr < 8:
                target = squares[nr * 8 + nf]
                if target:
                    if target == rook or target == queen:
                        return True
                    break
                nf += df
                nr += dr

        return False

    def is_in_check(self, color: int | None = None) -> bool:
        if color is None:
            color = self.turn
        king = self.king_sq[color]
        if king < 0:
            return False
        return self.is_square_attacked(king, color ^ 1)

    # ---------------------------------------------------------- make/unmake

    def make_move(self, move: tuple) -> None:
        frm, to, promo, flag = move
        squares = self.squares
        piece = squares[frm]
        color = color_of(piece)
        ptype = type_of(piece)

        captured = EMPTY
        cap_sq = to
        if flag == FLAG_EP:
            cap_sq = to - 8 if color == WHITE else to + 8
            captured = squares[cap_sq]
        elif squares[to] != EMPTY:
            captured = squares[to]

        self.undo_stack.append((
            captured,
            self.castling,
            self.ep,
            self.halfmove,
            self.hash,
            self.king_sq[0],
            self.king_sq[1],
            cap_sq,
        ))

        h = self.hash
        if self.ep != -1:
            h ^= ZOBRIST_EP[self.ep & 7]

        if self.castling:
            new_castling = (self.castling
                            & CASTLE_RIGHTS_MASK[frm]
                            & CASTLE_RIGHTS_MASK[to])
            if new_castling != self.castling:
                h ^= (ZOBRIST_CASTLING[self.castling]
                      ^ ZOBRIST_CASTLING[new_castling])
                self.castling = new_castling

        h ^= ZOBRIST_PIECE[piece][frm]
        squares[frm] = EMPTY

        if captured:
            h ^= ZOBRIST_PIECE[captured][cap_sq]
            squares[cap_sq] = EMPTY

        placed = make_piece(color, promo) if promo else piece
        squares[to] = placed
        h ^= ZOBRIST_PIECE[placed][to]

        if ptype == KING:
            self.king_sq[color] = to

        if flag == FLAG_CASTLE:
            if to == 6:
                rook_from, rook_to = 7, 5
            elif to == 2:
                rook_from, rook_to = 0, 3
            elif to == 62:
                rook_from, rook_to = 63, 61
            else:
                rook_from, rook_to = 56, 59
            rook = squares[rook_from]
            h ^= ZOBRIST_PIECE[rook][rook_from] ^ ZOBRIST_PIECE[rook][rook_to]
            squares[rook_from] = EMPTY
            squares[rook_to] = rook

        if flag == FLAG_DOUBLE:
            self.ep = (frm + to) >> 1
            h ^= ZOBRIST_EP[self.ep & 7]
        else:
            self.ep = -1

        if ptype == PAWN or captured:
            self.halfmove = 0
        else:
            self.halfmove += 1

        if color == BLACK:
            self.fullmove += 1

        self.turn ^= 1
        h ^= ZOBRIST_TURN
        self.hash = h
        self.history_hashes.append(h)

    def unmake_move(self, move: tuple) -> None:
        frm, to, promo, flag = move
        (captured, castling, ep, halfmove, hash_, kw, kb,
         cap_sq) = self.undo_stack.pop()
        self.history_hashes.pop()

        self.turn ^= 1
        color = self.turn
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.hash = hash_
        self.king_sq[0] = kw
        self.king_sq[1] = kb
        if color == BLACK:
            self.fullmove -= 1

        piece = self.squares[to]
        if promo:
            piece = make_piece(color, PAWN)
        self.squares[frm] = piece
        self.squares[to] = EMPTY
        if captured:
            self.squares[cap_sq] = captured

        if flag == FLAG_CASTLE:
            if to == 6:
                rook_from, rook_to = 7, 5
            elif to == 2:
                rook_from, rook_to = 0, 3
            elif to == 62:
                rook_from, rook_to = 63, 61
            else:
                rook_from, rook_to = 56, 59
            rook = self.squares[rook_to]
            self.squares[rook_to] = EMPTY
            self.squares[rook_from] = rook

    # ------------------------------------------------------------ draw rules

    def is_repetition(self, required: int = 1) -> bool:
        h = self.hash
        limit = min(self.halfmove, len(self.history_hashes) - 1)
        count = 0
        for i in range(1, limit + 1):
            if self.history_hashes[-1 - i] == h:
                count += 1
                if count >= required:
                    return True
        return False

    def has_insufficient_material(self) -> bool:
        minors = []
        for sq, piece in enumerate(self.squares):
            if not piece:
                continue
            ptype = type_of(piece)
            if ptype in (PAWN, ROOK, QUEEN):
                return False
            if ptype in (KNIGHT, BISHOP):
                minors.append((ptype, color_of(piece), (sq & 7) ^ (sq >> 3)))
        if not minors:
            return True
        if len(minors) == 1:
            return True
        if (len(minors) == 2
                and minors[0][0] == BISHOP
                and minors[1][0] == BISHOP
                and minors[0][2] == minors[1][2]):
            return True
        return False

    # ----------------------------------------------------------------- misc

    def copy(self) -> "Board":
        return Board(self.fen())

    def __str__(self) -> str:
        lines = []
        for rank in range(7, -1, -1):
            row = [CHAR_BY_PIECE.get(self.squares[rank * 8 + file], ".")
                   for file in range(8)]
            lines.append(f"{rank + 1} " + " ".join(row))
        lines.append("  a b c d e f g h")
        return "\n".join(lines)
