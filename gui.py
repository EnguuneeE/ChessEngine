"""Pygame GUI: play the engine in a window (or human vs human).

Usage:
    python gui.py                 start the GUI
    python gui.py --selftest      run a headless smoke test

Pieces render from assets/pieces/*.png (cburnett set, Wikimedia Commons,
BSD/GPL - see assets/pieces/LICENSE.txt); falls back to unicode glyphs, then
vector drawings.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time

import pygame

from chess_engine.board import (
    BLACK,
    Board,
    FLAG_CAPTURE,
    FLAG_EP,
    FLAG_PROMO_CAPTURE,
    QUEEN,
    ROOK,
    BISHOP,
    KNIGHT,
    PAWN,
    KING,
    START_FEN,
    WHITE,
    move_uci,
)
from chess_engine.movegen import legal_moves
from chess_engine.notation import move_to_san
from chess_engine.search import MATE, MATE_THRESHOLD, Searcher

# ----------------------------------------------------------------- constants

SQUARE = 80
BOARD_PX = SQUARE * 8
MARGIN = 16
PANEL_W = 330
PAD = 14
WINDOW_W = MARGIN + BOARD_PX + PANEL_W + MARGIN
WINDOW_H = MARGIN + BOARD_PX + MARGIN
PANEL_X = MARGIN + BOARD_PX + MARGIN
FPS = 60

LIGHT_SQ = (240, 217, 181)
DARK_SQ = (181, 136, 99)
FRAME = (46, 35, 27)

BG_TOP = (34, 34, 41)
BG_BOTTOM = (19, 19, 24)
CARD = (36, 36, 43)
CARD_EDGE = (58, 58, 68)

HL_LAST = (255, 235, 110, 80)
HL_SELECT = (95, 160, 255, 125)
HL_CHECK = (235, 60, 50, 135)
DOT_NORMAL = (30, 30, 30, 70)
CAPT_RING = (215, 55, 45, 165)

PANEL_FG = (236, 236, 240)
PANEL_DIM = (158, 158, 168)
BTN_BG = (54, 54, 63)
BTN_BG_HOVER = (70, 70, 82)
BTN_BG_DISABLED = (41, 41, 48)
BTN_FG_DISABLED = (124, 124, 133)
ACCENT = (122, 162, 255)
GOOD = (150, 210, 150)
WARN = (240, 170, 90)

ANIM_SLIDE = 0.17

LEVELS = [
    ("Level 1", 0.05, 2),
    ("Level 2", 0.15, 4),
    ("Level 3", 0.5, 6),
    ("Level 4", 1.2, 8),
    ("Level 5", 3.0, 12),
]
MODE_PVE = "Human vs Engine"
MODE_PVP = "Human vs Human"

GLYPHS_FILLED = {  # solid (black) unicode glyphs, recolored per side
    PAWN: "\u265F",
    KNIGHT: "\u265E",
    BISHOP: "\u265D",
    ROOK: "\u265C",
    QUEEN: "\u265B",
    KING: "\u265A",
}

OUTLINE_OFFSETS = [(dx, dy) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)
                   if dx * dx + dy * dy <= 5 and (dx, dy) != (0, 0)]


# ------------------------------------------------------------------- worker

class EngineThread(threading.Thread):
    """Runs searches in the background so the GUI never stalls."""

    def __init__(self, results: queue.Queue):
        super().__init__(daemon=True)
        self.tasks = queue.Queue()
        self.results = results
        self.board = Board(START_FEN)
        self.searcher = Searcher(self.board)

    def run(self) -> None:
        while True:
            task = self.tasks.get()
            if task[0] == "quit":
                return
            if task[0] == "clear":
                self.searcher.clear()
                continue
            if task[0] != "search":
                continue
            _, gen, fen, movetime, depth = task
            self.board.set_fen(fen)
            self.searcher.stop_flag = False

            def info_cb(d, s, pv, n, t, g=gen, f=fen):
                self.results.put(
                    ("info", g, f, d, s, n, t, [move_uci(m) for m in pv]))

            try:
                move, score, reached = self.searcher.search(
                    time_limit=movetime, max_depth=depth, info_callback=info_cb)
            finally:
                self.searcher.stop_flag = False
            if move is None:
                self.results.put(("best", gen, fen, None, score, reached, []))
            else:
                pv = [move_uci(m) for m in self.searcher.pv_line()]
                self.results.put(("best", gen, fen, move_uci(move),
                                  score, reached, pv))


# ---------------------------------------------------------------- piece art

ASSET_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "pieces")

ASSET_NAMES = {
    (WHITE, PAWN): "wp.png",
    (WHITE, KNIGHT): "wn.png",
    (WHITE, BISHOP): "wb.png",
    (WHITE, ROOK): "wr.png",
    (WHITE, QUEEN): "wq.png",
    (WHITE, KING): "wk.png",
    (BLACK, PAWN): "bp.png",
    (BLACK, KNIGHT): "bn.png",
    (BLACK, BISHOP): "bb.png",
    (BLACK, ROOK): "br.png",
    (BLACK, QUEEN): "bq.png",
    (BLACK, KING): "bk.png",
}


def _find_symbol_font():
    names = set(pygame.font.get_fonts())
    for candidate in ("segoeuisymbol", "symbola", "dejavusans", "opensymbol"):
        if candidate in names:
            return candidate
    return None


def _load_piece_assets(size: int):
    """Load the cburnett PNG set if present; None otherwise."""
    if not all(os.path.isfile(os.path.join(ASSET_DIR, name))
               for name in ASSET_NAMES.values()):
        return None
    try:
        out = {}
        for (color, ptype), name in ASSET_NAMES.items():
            surf = pygame.image.load(os.path.join(ASSET_DIR, name))
            surf = surf.convert_alpha()
            out[(color, ptype)] = pygame.transform.smoothscale(
                surf, (size, size))
        return out
    except (pygame.error, OSError):
        return None


class PieceRenderer:
    def __init__(self, size: int):
        self.size = size
        self.surfaces = {}
        self.assets = _load_piece_assets(int(size * 0.94))
        if self.assets is not None:
            self.font = None
            self.uses_glyphs = False
            self.uses_assets = True
            return
        self.uses_assets = False
        font_name = _find_symbol_font()
        if font_name:
            self.font = pygame.font.SysFont(font_name, int(size * 0.92))
            self.uses_glyphs = True
        else:
            self.font = None
            self.uses_glyphs = False

    def get(self, piece: int) -> pygame.Surface:
        if self.uses_assets:
            return self.assets[(piece >> 3, piece & 7)]
        surf = self.surfaces.get(piece)
        if surf is None:
            surf = self._render(piece)
            self.surfaces[piece] = surf
        return surf

    def _render(self, piece: int) -> pygame.Surface:
        color = piece >> 3
        ptype = piece & 7
        if self.uses_glyphs:
            return self._render_glyph(color, ptype)
        return self._render_vector(color, ptype)

    def _render_glyph(self, color: int, ptype: int) -> pygame.Surface:
        glyph = GLYPHS_FILLED[ptype]
        if color == WHITE:
            fill, rim = (247, 247, 250), (32, 32, 36)
        else:
            fill, rim = (30, 30, 33), (235, 235, 240)
        base = self.font.render(glyph, True, fill)
        outline = self.font.render(glyph, True, rim)
        w, h = base.get_size()
        pad = 4
        surf = pygame.Surface((w + 2 * pad, h + 2 * pad), pygame.SRCALPHA)
        for dx, dy in OUTLINE_OFFSETS:
            surf.blit(outline, (pad + dx, pad + dy))
        surf.blit(base, (pad, pad))
        return surf

    # ------------------------------------------------------- vector fallback

    def _render_vector(self, color: int, ptype: int) -> pygame.Surface:
        s = self.size
        surf = pygame.Surface((s, s), pygame.SRCALPHA)
        fill = (245, 245, 248) if color == WHITE else (25, 25, 27)
        edge = (35, 35, 38) if color == WHITE else (235, 235, 235)
        cx = cy = s // 2
        u = s / 8.0

        def circle(pos, r, col, width=0):
            pygame.draw.circle(surf, col, pos, int(r), width)

        def poly(points, col):
            pygame.draw.polygon(surf, col, [(x, y) for x, y in points])

        def rect(r, col, width=0):
            pygame.draw.rect(surf, col, pygame.Rect(r), width)

        if ptype == PAWN:
            circle((cx, cy - 2 * u), 1.2 * u, fill)
            circle((cx, cy - 2 * u), 1.2 * u, edge, 2)
            poly([(cx - 2.4 * u, cy + 3 * u), (cx + 2.4 * u, cy + 3 * u),
                  (cx + 1.3 * u, cy - 0.6 * u), (cx - 1.3 * u, cy - 0.6 * u)], fill)
            rect((cx - 2.4 * u, cy + 3.0 * u - 1, 4.8 * u, 1.1 * u), edge, 2)
        elif ptype == ROOK:
            for i in (-2.4, -0.9, 0.9, 2.4):
                rect((cx + i * u - 0.35 * u, cy - 4.0 * u, 0.7 * u, 1.0 * u), fill)
            rect((cx - 2.6 * u, cy - 3.2 * u, 5.2 * u, 1.4 * u), fill)
            rect((cx - 1.9 * u, cy - 1.8 * u, 3.8 * u, 0.8 * u), fill)
            poly([(cx - 2.2 * u, cy - 1.0 * u), (cx + 2.2 * u, cy - 1.0 * u),
                  (cx + 2.2 * u, cy + 3.2 * u), (cx - 2.2 * u, cy + 3.2 * u)], fill)
            rect((cx - 2.6 * u, cy + 3.2 * u, 5.2 * u, 1.0 * u), fill)
        elif ptype == BISHOP:
            circle((cx, cy), 2.2 * u, fill)
            circle((cx, cy), 2.2 * u, edge, 2)
            circle((cx, cy - 3.1 * u), 0.7 * u, fill)
            poly([(cx - 2.4 * u, cy + 3.4 * u), (cx + 2.4 * u, cy + 3.4 * u),
                  (cx + 1.4 * u, cy + 1.8 * u), (cx - 1.4 * u, cy + 1.8 * u)], fill)
        elif ptype == KNIGHT:
            poly([(cx - 2.2 * u, cy + 3.2 * u), (cx + 2.2 * u, cy + 3.2 * u),
                  (cx + 2.2 * u, cy + 1.2 * u), (cx + 0.6 * u, cy - 1.0 * u),
                  (cx + 1.2 * u, cy - 2.6 * u), (cx - 0.4 * u, cy - 3.4 * u),
                  (cx - 2.0 * u, cy - 0.8 * u), (cx - 2.4 * u, cy + 1.0 * u)], fill)
            circle((cx + 0.9 * u, cy - 2.2 * u), 0.3 * u, edge)
        elif ptype == QUEEN:
            for dx in (-3.0, -1.5, 0.0, 1.5, 3.0):
                circle((cx + dx * u, cy - 2.6 * u), 0.55 * u, fill)
            poly([(cx - 3.0 * u, cy - 2.3 * u), (cx + 3.0 * u, cy - 2.3 * u),
                  (cx + 2.4 * u, cy + 2.5 * u), (cx - 2.4 * u, cy + 2.5 * u)], fill)
            rect((cx - 2.9 * u, cy + 2.5 * u, 5.8 * u, 1.2 * u), fill)
        elif ptype == KING:
            rect((cx - 0.45 * u, cy - 4.4 * u, 0.9 * u, 2.4 * u), fill)
            rect((cx - 1.2 * u, cy - 3.5 * u, 2.4 * u, 0.9 * u), fill)
            poly([(cx - 2.2 * u, cy - 1.2 * u), (cx + 2.2 * u, cy - 1.2 * u),
                  (cx + 2.2 * u, cy + 2.4 * u), (cx - 2.2 * u, cy + 2.4 * u)], fill)
            rect((cx - 2.6 * u, cy + 2.4 * u, 5.2 * u, 1.2 * u), fill)
        pygame.draw.rect(surf, edge, surf.get_rect(), 1)
        return surf


# ------------------------------------------------------------------- button

class Button:
    def __init__(self, rect, key):
        self.rect = pygame.Rect(rect)
        self.key = key


# ---------------------------------------------------------------------- app

class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Chess Engine")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("segoeui", 16)
        self.font_mid = pygame.font.SysFont("segoeui", 15, bold=True)
        self.font_small = pygame.font.SysFont("segoeui", 13)
        self.font_coord = pygame.font.SysFont("segoeui", 12, bold=True)
        self.font_big = pygame.font.SysFont("segoeui", 24, bold=True)
        self.pieces = PieceRenderer(int(SQUARE * 0.94))
        self.bg = self._build_bg()

        self.board = Board(START_FEN)
        self.moves = []
        self.san_pairs = []
        self.legal_cache = legal_moves(self.board)

        self.mode = MODE_PVE
        self.level = 2
        self.human_white = True
        self.flip = False

        self.selected = None
        self.targets = []
        self.drag_from = None
        self.drag_pos = (0, 0)
        self.promotion = None
        self.promotion_moves = []
        self.game_over = None
        self.last_move = None
        self.anim = None

        self.worker = None
        self.results = queue.Queue()
        self.engine_gen = 0
        self.engine_search_key = None
        self.engine_info = None
        self.pending_result = None
        self.think_frame = 0
        self.move_scroll = 0

        self.buttons = self._build_buttons()
        self.new_game()

    # ------------------------------------------------------------- geometry

    def board_rect(self):
        return pygame.Rect(MARGIN, MARGIN, BOARD_PX, BOARD_PX)

    def panel_rect(self):
        return pygame.Rect(PANEL_X, MARGIN, PANEL_W, BOARD_PX)

    def _disp(self, sq):
        """Map a square to (display_row, display_col); white sits at the bottom."""
        r, f = sq >> 3, sq & 7
        if self.flip:
            r, f = 7 - r, 7 - f
        return 7 - r, f

    def disp_square(self, drow, dcol):
        r, f = 7 - drow, dcol
        if self.flip:
            r, f = 7 - r, 7 - f
        return r * 8 + f

    def square_rect(self, sq):
        drow, dcol = self._disp(sq)
        return pygame.Rect(MARGIN + dcol * SQUARE, MARGIN + drow * SQUARE,
                           SQUARE, SQUARE)

    def pixel_square(self, pos):
        if not self.board_rect().collidepoint(pos):
            return None
        drow = (pos[1] - MARGIN) // SQUARE
        dcol = (pos[0] - MARGIN) // SQUARE
        return self.disp_square(int(drow), int(dcol))

    def _build_bg(self):
        bg = pygame.Surface((WINDOW_W, WINDOW_H))
        for y in range(WINDOW_H):
            t = y / max(1, WINDOW_H - 1)
            color = [int(BG_TOP[ch] + (BG_BOTTOM[ch] - BG_TOP[ch]) * t)
                     for ch in range(3)]
            pygame.draw.line(bg, color, (0, y), (WINDOW_W, y))
        return bg

    # -------------------------------------------------------------- buttons

    def _build_buttons(self):
        pr = self.panel_rect()
        x0 = pr.x + PAD
        bw, bh, gap = (PANEL_W - 2 * PAD - 8) // 2, 32, 8
        y0 = pr.y + 76
        grid = {}
        for i, key in enumerate(("new", "flip", "undo", "stop")):
            col, row = i % 2, i // 2
            grid[key] = Button((x0 + (bw + gap) * col, y0 + (bh + gap) * row,
                                bw, bh), key)
        y2 = y0 + 2 * (bh + gap) + 6
        for i, key in enumerate(("mode", "side", "level")):
            grid[key] = Button((x0, y2 + i * (bh + 5), PANEL_W - 2 * PAD, bh - 2),
                               key)
        list_y = y2 + 3 * (bh + 3) + 12
        list_h = pr.bottom - list_y - 86
        self.move_list_rect = pygame.Rect(x0, list_y, PANEL_W - 2 * PAD, list_h)
        return grid

    def button_label(self, key):
        if key == "new":
            return "New Game"
        if key == "flip":
            return "Flip Board"
        if key == "undo":
            return "Undo Move"
        if key == "stop":
            return "Stop Search"
        if key == "mode":
            return self.mode
        if key == "side":
            return "Engine plays White" if not self.human_white \
                else "Engine plays Black"
        if key == "level":
            note = "  (PvP)" if self.mode == MODE_PVP else ""
            return f"Strength: {LEVELS[self.level][0]}{note}"
        return key

    def button_enabled(self, key):
        if key == "stop":
            return self.engine_search_key is not None
        if key == "undo":
            return bool(self.moves)
        if key in ("side", "level"):
            return self.mode == MODE_PVE
        return True

    def on_button(self, key):
        if key == "new":
            self.new_game()
        elif key == "flip":
            self.flip = not self.flip
        elif key == "undo":
            self.undo_move()
        elif key == "stop":
            self.interrupt_engine()
        elif key == "mode":
            self.interrupt_engine()
            self.mode = MODE_PVP if self.mode == MODE_PVE else MODE_PVE
            self.refresh_after_state_change()
        elif key == "side":
            self.interrupt_engine()
            self.human_white = not self.human_white
            self.refresh_after_state_change()
        elif key == "level":
            self.level = (self.level + 1) % len(LEVELS)

    # ------------------------------------------------------------ game flow

    def human_turn(self):
        if self.game_over:
            return False
        if self.mode == MODE_PVP:
            return True
        return (self.board.turn == WHITE) == self.human_white

    def new_game(self):
        self.interrupt_engine()
        self.board = Board(START_FEN)
        self.moves = []
        self.san_pairs = []
        self.selected = None
        self.targets = []
        self.drag_from = None
        self.promotion = None
        self.last_move = None
        self.engine_info = None
        self.anim = None
        self.move_scroll = 0
        self.refresh_after_state_change(start=True)

    def refresh_after_state_change(self, start=False):
        self.legal_cache = legal_moves(self.board)
        self.selected = None
        self.targets = []
        self.promotion = None
        self.game_over = self.detect_game_over()
        if self.mode == MODE_PVE and self.game_over is None:
            if start and not self.human_position_now():
                self.flip = self.board.turn == WHITE  # engine moves first
            if not self.human_turn():
                self.maybe_ask_engine()
            elif self.mode == MODE_PVE:
                self.flip = self.board.turn != WHITE

    def human_position_now(self):
        return (self.board.turn == WHITE) == self.human_white

    def detect_game_over(self):
        if not self.legal_cache:
            if self.board.is_in_check():
                winner = "White" if self.board.turn == BLACK else "Black"
                return f"Checkmate - {winner} wins"
            return "Draw - stalemate"
        if self.board.has_insufficient_material():
            return "Draw - insufficient material"
        if self.board.halfmove >= 100:
            return "Draw - 50 move rule"
        if self.board.is_repetition(2):
            return "Draw - threefold repetition"
        return None

    def interrupt_engine(self):
        if self.worker is not None:
            self.worker.searcher.stop_flag = True
        self.engine_gen += 1
        self.engine_search_key = None
        self.pending_result = None
        self.engine_info = None

    def maybe_ask_engine(self):
        if self.mode != MODE_PVE or self.game_over is not None or self.human_turn():
            return
        if self.engine_search_key is not None:
            return
        if self.worker is None:
            self.worker = EngineThread(self.results)
            self.worker.start()
        self.engine_gen += 1
        self.engine_search_key = (self.engine_gen, self.board.fen())
        _, movetime, depth = LEVELS[self.level]
        self.worker.tasks.put(("search", self.engine_gen, self.board.fen(),
                               movetime, depth))

    def apply_move(self, move, san=None, animate=True):
        if san is None:
            san = move_to_san(self.board, move)
        self.anim = self._capture_anim(move) if animate else None
        self.last_move = move
        self.board.make_move(move)
        self.moves.append(move)
        if self.board.turn == BLACK:
            self.san_pairs.append([str(1 + len(self.san_pairs)), san, ""])
        else:
            self.san_pairs[-1][2] = san
        self.engine_info = None
        self.move_scroll = max(0, len(self.san_pairs) - self._ml_visible())
        self.refresh_after_state_change()

    def _capture_anim(self, move):
        """Snapshot piece positions (pre-move) for slide/fade animation."""
        frm, to, promo, flag = move
        squares = self.board.squares
        piece = squares[frm]
        slides = [(piece, frm, to)]
        fades = []
        if flag == FLAG_EP:
            cap_sq = to - 8 if (piece >> 3) == WHITE else to + 8
            fades.append((squares[cap_sq], cap_sq))
        elif squares[to]:
            fades.append((squares[to], to))
        if flag == 4:  # FLAG_CASTLE
            rook_from, rook_to = {6: (7, 5), 2: (0, 3),
                                  62: (63, 61), 56: (56, 59)}[to]
            slides.append((squares[rook_from], rook_from, rook_to))
        return {"slides": slides, "fades": fades,
                "t0": time.monotonic(), "dur": ANIM_SLIDE}

    def undo_move(self):
        if not self.moves:
            return
        self.interrupt_engine()
        self.anim = None
        self._pop_ply()
        if self.mode == MODE_PVE and self.moves and not self.human_position_now():
            self._pop_ply()
        self.engine_info = None
        self.refresh_after_state_change()

    def _pop_ply(self):
        move = self.moves.pop()
        self.board.unmake_move(move)
        if self.board.turn == WHITE:  # undid a white move -> row disappears
            self.san_pairs.pop()
        else:
            self.san_pairs[-1][2] = ""

    # -------------------------------------------------------------- events

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.selected, self.drag_from, self.targets = None, None, []
            self.promotion = None
        elif event.type == pygame.MOUSEWHEEL:
            visible = self._ml_visible()
            lim = max(0, len(self.san_pairs) - visible)
            self.move_scroll = max(0, min(self.move_scroll - event.y, lim))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if event.pos[0] >= PANEL_X:
                self.handle_panel_click(event.pos)
            else:
                self.click_board(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.mouse_up(event.pos)
        elif event.type == pygame.MOUSEMOTION:
            self.drag_pos = event.pos

    def handle_panel_click(self, pos):
        for btn in self.buttons.values():
            if btn.rect.collidepoint(pos):
                if self.button_enabled(btn.key):
                    self.on_button(btn.key)
                return

    def click_board(self, pos):
        if self.promotion is not None:
            self.promotion_click(pos)
            return
        if not self.human_turn():
            return
        sq = self.pixel_square(pos)
        if sq is None:
            return
        piece = self.board.squares[sq]
        own = piece and (piece >> 3) == self.board.turn
        if self.selected is not None:
            move = self.find_move(self.selected, sq)
            if move is not None:
                self.commit_user_move(self.selected, sq, move)
                return
        if own:
            self.select_piece(sq, pos)
        else:
            self.selected, self.targets, self.drag_from = None, [], None

    def mouse_up(self, pos):
        if self.promotion is not None:
            self.promotion_click(pos)
            return
        if self.drag_from is None:
            return
        start, self.drag_from = self.drag_from, None
        sq = self.pixel_square(pos)
        if sq is None or sq == start:
            return
        move = self.find_move(start, sq)
        if move is not None:
            self.commit_user_move(start, sq, move, animate=False)

    def select_piece(self, sq, pos):
        self.selected = sq
        self.targets = [m for m in self.legal_cache if m[0] == sq]
        self.drag_from = sq
        self.drag_pos = pos

    def find_move(self, frm, to):
        for move in self.legal_cache:
            if move[0] == frm and move[1] == to:
                return move
        return None

    def commit_user_move(self, frm, to, move, animate=True):
        promo_moves = [m for m in self.legal_cache
                       if m[0] == frm and m[1] == to and m[2]]
        self.selected, self.targets, self.drag_from = None, [], None
        if promo_moves:
            self.promotion_moves = promo_moves
            self.promotion = self.build_promotion_dialog(to)
            return
        self.apply_move(move, animate=animate)

    def build_promotion_dialog(self, to):
        r = self.square_rect(to)
        downward = r.y < MARGIN + 3 * SQUARE
        y = r.y if downward else r.y - 3 * SQUARE
        choices = [(ptype, pygame.Rect(r.x, y + i * SQUARE, SQUARE, SQUARE))
                   for i, ptype in enumerate((QUEEN, ROOK, KNIGHT, BISHOP))]
        box = pygame.Rect(r.x, y, SQUARE, 4 * SQUARE)
        return (box, choices, downward)

    def promotion_click(self, pos):
        box, choices, _ = self.promotion
        if not box.collidepoint(pos):
            self.promotion = None
            return
        for ptype, r in choices:
            if r.collidepoint(pos):
                for move in self.promotion_moves:
                    if move[2] == ptype:
                        self.promotion = None
                        self.apply_move(move)
                        return

    # ------------------------------------------------------ engine results

    def poll_engine(self):
        while True:
            try:
                result = self.results.get_nowait()
            except queue.Empty:
                return
            kind = result[0]
            if kind == "info":
                _, gen, fen, depth, _score, nodes, elapsed, pv = result
                if self.engine_search_key == (gen, fen):
                    self.engine_info = (depth, nodes, elapsed, pv, _score)
            else:
                _, gen, fen, uci, _score, _reached, pv = result
                if self.engine_search_key != (gen, fen):
                    continue
                self.engine_search_key = None
                self.pending_result = (fen, uci)
            if self.pending_result is None:
                continue
            fen, uci = self.pending_result
            if self.board.fen() != fen or uci is None:
                self.pending_result = None
                self.refresh_after_state_change()
                return
            move = next((m for m in self.legal_cache if move_uci(m) == uci), None)
            self.pending_result = None
            if move is None:
                self.refresh_after_state_change()
                return
            self.apply_move(move)
            return  # one engine move per frame to keep redraws smooth

    # ----------------------------------------------------------------- draw

    def run(self):
        self.running = True
        while self.running:
            self.clock.tick(FPS)
            self.tick()
            for event in pygame.event.get():
                self.handle_event(event)
            self.draw()
        self.shutdown()

    def run_frames(self, frames):
        self.running = True
        for _ in range(frames):
            self.clock.tick(FPS)
            self.tick()
            self.draw()
            if not self.running:
                break

    def tick(self):
        self.think_frame = (self.think_frame + 1) % 32
        if self.anim is not None:
            if time.monotonic() - self.anim["t0"] >= self.anim["dur"]:
                self.anim = None
        if self.worker is not None:
            self.poll_engine()
        self.maybe_ask_engine()

    def shutdown(self):
        if self.worker is not None:
            self.worker.tasks.put(("quit",))
            self.worker.searcher.stop_flag = True
        pygame.quit()

    def draw(self):
        self.screen.blit(self.bg, (0, 0))
        self.draw_board()
        self.draw_panel()
        pygame.display.flip()

    def draw_board(self):
        br = self.board_rect()
        shadow = pygame.Surface((BOARD_PX + 30, BOARD_PX + 30), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 85),
                         pygame.Rect(15, 17, BOARD_PX + 10, BOARD_PX + 10),
                         border_radius=14)
        self.screen.blit(shadow, (br.x - 15, br.y - 15))
        pygame.draw.rect(self.screen, FRAME, br.inflate(10, 10),
                         border_radius=10)
        pygame.draw.rect(self.screen, (12, 10, 9), br.inflate(10, 10),
                         width=1, border_radius=10)

        prog = self._anim_progress()
        if prog is None:
            self.anim = None
        skip = self._anim_skip_squares() if prog is not None else set()

        for sq in range(64):
            color = LIGHT_SQ if ((sq >> 3) + (sq & 7)) % 2 == 0 else DARK_SQ
            pygame.draw.rect(self.screen, color, self.square_rect(sq))

        overlay = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
        if self.last_move is not None:
            for sq in (self.last_move[0], self.last_move[1]):
                self._paint(overlay, self.square_rect(sq), HL_LAST)
        if self.legal_cache and self.board.is_in_check():
            king_sq = self.board.king_sq[self.board.turn]
            self._paint(overlay, self.square_rect(king_sq), HL_CHECK)
        if self.selected is not None:
            self._paint(overlay, self.square_rect(self.selected), HL_SELECT)
            for move in self.targets:
                rect = self.square_rect(move[1])
                cx, cy = rect.centerx - MARGIN, rect.centery - MARGIN
                if move[3] in (FLAG_CAPTURE, FLAG_EP, FLAG_PROMO_CAPTURE):
                    pygame.draw.circle(overlay, CAPT_RING, (cx, cy),
                                       SQUARE // 2 - 5, 6)
                else:
                    pygame.draw.circle(overlay, DOT_NORMAL, (cx, cy), 10)

        for sq in range(64):
            piece = self.board.squares[sq]
            if piece and sq != self.drag_from and sq not in skip:
                surf = self.pieces.get(piece)
                self.screen.blit(surf, surf.get_rect(
                    center=self.square_rect(sq).center))

        self.screen.blit(overlay, (MARGIN, MARGIN))

        if prog is not None:
            self.draw_anim(prog)

        if self.drag_from is not None:
            piece = self.board.squares[self.drag_from]
            if piece:
                surf = self.pieces.get(piece).copy()
                surf.set_alpha(210)
                self.screen.blit(surf, surf.get_rect(center=self.drag_pos))

        self.draw_coordinates()
        if self.promotion is not None:
            self.draw_promotion()
        elif self.game_over is not None and self.anim is None:
            self.draw_game_over_banner()

    def _anim_progress(self):
        if self.anim is None:
            return None
        p = (time.monotonic() - self.anim["t0"]) / self.anim["dur"]
        if p >= 1.0:
            return None
        return 1.0 - (1.0 - p) ** 3

    def _anim_skip_squares(self):
        skip = set()
        for _, frm, to in self.anim["slides"]:
            skip.add(to)
        for _, sq in self.anim["fades"]:
            skip.add(sq)
        return skip

    def draw_anim(self, prog):
        for piece, frm, to in self.anim["slides"]:
            surf = self.pieces.get(piece)
            start = self.square_rect(frm).center
            end = self.square_rect(to).center
            x = start[0] + (end[0] - start[0]) * prog
            y = start[1] + (end[1] - start[1]) * prog
            self.screen.blit(surf, surf.get_rect(center=(int(x), int(y))))
        alpha = int(255 * (1.0 - prog))
        for piece, sq in self.anim["fades"]:
            surf = self.pieces.get(piece).copy()
            surf.set_alpha(alpha)
            self.screen.blit(surf, surf.get_rect(
                center=self.square_rect(sq).center))

    @staticmethod
    def _paint(overlay, rect, color):
        x = rect.x - MARGIN
        y = rect.y - MARGIN
        pygame.draw.rect(overlay, color, pygame.Rect(x, y, SQUARE, SQUARE))

    def draw_coordinates(self):
        for dcol in range(8):
            sq = self.disp_square(7, dcol)
            light = ((sq >> 3) + (sq & 7)) % 2 == 0
            color = (128, 95, 70) if light else (244, 230, 212)
            text = self.font_coord.render("abcdefgh"[sq & 7], True, color)
            self.screen.blit(text, text.get_rect(
                topleft=(MARGIN + dcol * SQUARE + SQUARE - 12,
                         MARGIN + 7 * SQUARE + SQUARE - 15)))
        for drow in range(8):
            sq = self.disp_square(drow, 0)
            light = ((sq >> 3) + (sq & 7)) % 2 == 0
            color = (128, 95, 70) if light else (244, 230, 212)
            text = self.font_coord.render("12345678"[sq >> 3], True, color)
            self.screen.blit(text, text.get_rect(
                topleft=(MARGIN + 4, MARGIN + drow * SQUARE + 4)))

    def draw_game_over_banner(self):
        if self.game_over.startswith("Draw"):
            tcol = (214, 214, 220)
        elif (self.mode == MODE_PVE
              and ("White" in self.game_over) != self.human_white):
            tcol = (235, 150, 150)  # you lost
        else:
            tcol = (185, 225, 170)
        bar = pygame.Surface((BOARD_PX - 140, 52), pygame.SRCALPHA)
        bar.fill((14, 13, 15, 205))
        x, y = MARGIN + 70, MARGIN + BOARD_PX // 2 - 26
        self.screen.blit(bar, (x, y))
        pygame.draw.rect(self.screen, (14, 13, 15),
                         pygame.Rect(x, y, bar.get_width(), bar.get_height()),
                         width=1)
        text = self.font_big.render(self.game_over, True, tcol)
        self.screen.blit(text, text.get_rect(
            center=(MARGIN + BOARD_PX // 2, MARGIN + BOARD_PX // 2)))

    def draw_promotion(self):
        box, choices, _ = self.promotion
        shadow = pygame.Surface((box.width + 16, box.height + 16), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 110))
        self.screen.blit(shadow, (box.x - 6, box.y - 4))
        pygame.draw.rect(self.screen, (250, 249, 244), box, border_radius=10)
        pygame.draw.rect(self.screen, (52, 52, 60), box, width=1, border_radius=10)
        mouse = pygame.mouse.get_pos()
        for ptype, r in choices:
            piece = (self.board.turn << 3) | ptype
            surf = self.pieces.get(piece)
            if r.collidepoint(mouse):
                pygame.draw.rect(self.screen, (233, 220, 196), r)
            self.screen.blit(surf, surf.get_rect(center=r.center))
            pygame.draw.rect(self.screen, (214, 205, 188), r, 1)
        pygame.draw.rect(self.screen, (52, 52, 60), box, 2, border_radius=10)

    def draw_panel(self):
        pr = self.panel_rect()
        shadow = pygame.Surface((PANEL_W + 22, BOARD_PX + 22), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 80),
                         pygame.Rect(11, 13, PANEL_W, BOARD_PX), border_radius=14)
        self.screen.blit(shadow, (pr.x - 11, pr.y - 11))
        pygame.draw.rect(self.screen, CARD, pr, border_radius=12)
        pygame.draw.rect(self.screen, CARD_EDGE, pr, width=1, border_radius=12)

        pygame.draw.rect(self.screen, ACCENT,
                         pygame.Rect(pr.x + PAD, pr.y + 17, 4, 20),
                         border_radius=2)
        title = self.font_big.render("Chess Engine", True, PANEL_FG)
        self.screen.blit(title, title.get_rect(
            midleft=(pr.x + PAD + 12, pr.y + 27)))

        status = self.status_text()
        scol = self.status_color()
        f = self.font
        surf = f.render(status, True, scol)
        if surf.get_width() > PANEL_W - 2 * PAD:
            f = self.font_small
            surf = f.render(status, True, scol)
        self.screen.blit(surf, surf.get_rect(
            topleft=(pr.x + PAD, pr.y + 52)))

        mouse = pygame.mouse.get_pos()
        for btn in self.buttons.values():
            self.draw_button(btn, mouse)

        self.draw_move_list(pr)

        footer = self.move_list_rect.bottom + 10
        info = self.engine_info_text()
        if info:
            surf = self.font_small.render(info, True, PANEL_DIM)
            self.screen.blit(surf, surf.get_rect(
                topleft=(pr.x + PAD, footer)))
        pv = self.engine_pv_text()
        for row in range(3):
            if not pv:
                break
            surf = self.font_small.render(pv[:46], True, PANEL_DIM)
            self.screen.blit(surf, surf.get_rect(
                topleft=(pr.x + PAD, footer + 17 + row * 16)))
            pv = pv[46:]

    def draw_button(self, btn, mouse):
        enabled = self.button_enabled(btn.key)
        hover = enabled and btn.rect.collidepoint(mouse)
        color = BTN_BG_HOVER if hover else (
            BTN_BG if enabled else BTN_BG_DISABLED)
        pygame.draw.rect(self.screen, color, btn.rect, border_radius=7)
        pygame.draw.rect(self.screen, CARD_EDGE, btn.rect, width=1,
                         border_radius=7)
        label = self.button_label(btn.key)
        s = self.font_mid.render(label, True,
                                 PANEL_FG if enabled else BTN_FG_DISABLED)
        while s.get_width() > btn.rect.w - 14 and len(label) > 4:
            label = label[:-1]
            s = self.font_mid.render(
                label + "...", True,
                PANEL_FG if enabled else BTN_FG_DISABLED)
        self.screen.blit(s, s.get_rect(center=btn.rect.center))

    def status_color(self):
        if self.game_over:
            return WARN if self.game_over.startswith("Draw") else GOOD
        if self.engine_search_key is not None:
            return ACCENT
        if self.legal_cache and self.board.is_in_check():
            return WARN
        return PANEL_FG

    def status_text(self):
        if self.game_over:
            return self.game_over
        if self.mode == MODE_PVP:
            side = "White" if self.board.turn == WHITE else "Black"
            text = f"{side} to move"
        else:
            if self.engine_search_key is not None:
                spinner = "-\\|/"[(self.think_frame // 8) % 4]
                depth = self.engine_info[0] if self.engine_info else 0
                text = f"Engine thinking {spinner}   depth {depth}"
            else:
                you = "White" if self.human_white else "Black"
                text = f"Your move ({you})"
        if self.legal_cache and self.board.is_in_check():
            text += "  [check]"
        return text

    def engine_info_text(self):
        if self.engine_info is None:
            return None
        depth, nodes, elapsed, pv, score = self.engine_info
        nps = nodes / elapsed if elapsed > 0 else 0.0
        if abs(score) >= MATE_THRESHOLD:
            plies = MATE - abs(score)
            moves_to_mate = max(1, (plies + 1) // 2)
            sign = "+" if score > 0 else "-"
            score_s = f"{sign}mate in {moves_to_mate}"
        else:
            score_s = f"{score / 100.0:+.2f}"
        return (f"depth {depth}   nodes {nodes:,}   "
                f"{nps / 1000.0:.0f} kn/s   score {score_s}")

    def engine_pv_text(self):
        if self.engine_info is None:
            return ""
        return " ".join(self.engine_info[3])

    def draw_move_list(self, pr):
        r = self.move_list_rect
        pygame.draw.rect(self.screen, (26, 26, 31), r, border_radius=8)
        pygame.draw.rect(self.screen, CARD_EDGE, r, width=1, border_radius=8)
        row_h = 19
        visible = self._ml_visible()
        lim = max(0, len(self.san_pairs) - visible)
        self.move_scroll = max(0, min(self.move_scroll, lim))
        last = len(self.san_pairs) - 1
        for i in range(self.move_scroll,
                       min(len(self.san_pairs), self.move_scroll + visible)):
            num, white, black = self.san_pairs[i]
            y = r.y + 5 + (i - self.move_scroll) * row_h
            if i == last:
                pygame.draw.rect(self.screen, (44, 44, 54),
                                 pygame.Rect(r.x + 1, y - 1, r.w - 2, row_h - 1))
            elif i % 2 == 1:
                pygame.draw.rect(self.screen, (31, 31, 37),
                                 pygame.Rect(r.x + 1, y - 1, r.w - 2, row_h - 1))
            x_num = self.font_small.render(f"{num}.", True, PANEL_DIM)
            self.screen.blit(x_num, x_num.get_rect(topright=(r.x + 46, y)))
            col_x = r.x + 56
            for text in (white, black):
                surf = self.font_small.render(text, True, PANEL_FG)
                self.screen.blit(surf, (col_x, y))
                col_x += 80
            if i == last:
                pygame.draw.rect(self.screen, ACCENT,
                                 pygame.Rect(r.x + 1, y - 1, 3, row_h - 1))
        if len(self.san_pairs) > visible:
            track = pygame.Rect(r.right - 8, r.y + 5, 4, r.height - 10)
            thumb_h = max(26, int(track.height * visible / len(self.san_pairs)))
            frac = self.move_scroll / max(1, lim)
            thumb_y = track.y + int((track.height - thumb_h) * frac)
            pygame.draw.rect(self.screen, (52, 52, 62), track, border_radius=2)
            pygame.draw.rect(self.screen, (125, 125, 136),
                             pygame.Rect(track.x, thumb_y, track.w, thumb_h),
                             border_radius=2)

    def _ml_visible(self):
        return max(1, (self.move_list_rect.height - 10) // 19)


# -------------------------------------------------------------------- entry

def run_gui():
    App().run()


def selftest():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    app = App()

    # play one human move, let the engine increment its window
    move = next(m for m in app.legal_cache if move_uci(m) == "e2e4")
    app.apply_move(move)
    assert len(app.moves) == 1

    level_saved = app.level
    app.level = 0  # fastest level for the smoke test
    app.run_frames(180)
    assert len(app.moves) >= 2, "engine should have replied"
    assert app.game_over is None

    app.undo_move()
    app.run_frames(30)
    app.level = level_saved
    app.on_button("flip")
    app.on_button("flip")
    app.on_button("mode")
    app.on_button("mode")
    app.new_game()
    app.run_frames(30)
    app.shutdown()
    print("gui selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run_gui()
