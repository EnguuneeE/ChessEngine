"""Interactive command line play."""

from __future__ import annotations

from .board import BLACK, START_FEN, WHITE, Board, move_uci
from .movegen import legal_moves
from .notation import move_to_san, parse_move_input
from .search import Searcher

HELP_TEXT = """Commands:
  help    show this help
  new     start a new game
  undo    take back your last move (and the engine's reply)
  fen     print the current FEN
  quit    exit

Moves may be entered in UCI (e2e4, e7e8q) or SAN (Nf3, exd5, O-O)."""


def play(human_color: int = WHITE, movetime: float = 1.5) -> None:
    board = Board()
    searcher = Searcher(board)
    game_moves = []

    color_name = "White" if human_color == WHITE else "Black"
    print("PyChessEngine")
    print(f"You play {color_name}. Type 'help' for commands.")

    while True:
        print()
        print(board)
        moves = legal_moves(board)

        if not moves:
            if board.is_in_check():
                winner = "Black" if board.turn == WHITE else "White"
                print(f"Checkmate! {winner} wins.")
            else:
                print("Stalemate - draw.")
            return
        if board.halfmove >= 100:
            print("Draw by the 50-move rule.")
            return
        if board.is_repetition(required=2):
            print("Draw by threefold repetition.")
            return
        if board.has_insufficient_material():
            print("Draw by insufficient material.")
            return

        if board.turn == human_color:
            print("Legal moves: " + ", ".join(move_to_san(board, m) for m in moves))
            try:
                text = input("Your move: ").strip()
            except EOFError:
                print()
                return
            lowered = text.lower()

            if lowered in ("quit", "exit", "q"):
                return
            if lowered == "help":
                print(HELP_TEXT)
                continue
            if lowered == "new":
                board.set_fen(START_FEN)
                game_moves.clear()
                searcher.clear()
                continue
            if lowered == "fen":
                print(board.fen())
                continue
            if lowered == "undo":
                count = 2 if len(game_moves) >= 2 else len(game_moves)
                for _ in range(count):
                    board.unmake_move(game_moves.pop())
                continue

            move = parse_move_input(board, text, moves)
            if move is None:
                print("Illegal or unrecognized move.")
                continue

            board.make_move(move)
            game_moves.append(move)
        else:
            print("Engine is thinking...")
            best, score, depth = searcher.search(time_limit=movetime)
            if best is None:
                print("Engine has no legal move.")
                return
            san = move_to_san(board, best)
            print(f"Engine plays {san} ({move_uci(best)}) "
                  f"[depth {depth}, score {score}]")
            board.make_move(best)
            game_moves.append(best)
