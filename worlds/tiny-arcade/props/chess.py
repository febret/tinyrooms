"""World-authored chess rules for The Arcade's chess room.

The server core only supplies a generic grid board and a place to persist opaque
state. Everything below -- legal moves, turns, rewards, and reset permission --
belongs to this world script.
"""

from __future__ import annotations

from typing import Any

FILES = "abcdefgh"
PIECE_VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}
RESET_POWERS = ("admin", "moderator", "game-master")
WIN_KUDOS = 3
MOVE_LIMIT = 50
MOVE_ENERGY_COST = 5
KNIGHT_DELTAS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_DELTAS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
SLIDING_DIRECTIONS = {
    "B": ((1, 1), (1, -1), (-1, 1), (-1, -1)),
    "R": ((1, 0), (-1, 0), (0, 1), (0, -1)),
    "Q": ((1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)),
}


def _index(square: str) -> int:
    return (8 - int(square[1])) * 8 + FILES.index(square[0])


def _square(index: int) -> str:
    return f"{FILES[index % 8]}{8 - index // 8}"


def _file_rank(index: int) -> tuple[int, int]:
    return index % 8, 7 - index // 8


def _idx(file: int, rank: int) -> int:
    return (7 - rank) * 8 + file


def _inside(file: int, rank: int) -> bool:
    return 0 <= file < 8 and 0 <= rank < 8


def _color(piece: dict[str, str] | None) -> str:
    return piece["code"][0] if piece else ""


def _kind(piece: dict[str, str] | None) -> str:
    return piece["code"][1] if piece else ""


def _opponent(color: str) -> str:
    return "b" if color == "w" else "w"


def _initial_board() -> list[dict[str, str] | None]:
    board: list[dict[str, str] | None] = [None] * 64
    back_rank = ("R", "N", "B", "Q", "K", "B", "N", "R")
    for file, kind in enumerate(back_rank):
        board[file] = {"id": f"b{kind}{file}", "code": f"b{kind}"}
        board[56 + file] = {"id": f"w{kind}{file}", "code": f"w{kind}"}
    for file in range(8):
        board[8 + file] = {"id": f"bP{file}", "code": "bP"}
        board[48 + file] = {"id": f"wP{file}", "code": "wP"}
    return board


def _initial_state(context) -> dict[str, Any]:
    return {
        "board": _initial_board(),
        "turn": "w",
        "castling": {"wK": True, "wQ": True, "bK": True, "bQ": True},
        "en_passant": "",
        "halfmove": 0,
        "fullmove": 1,
        "last_move": None,
        "started_at": context.now.isoformat(),
        "move_number": 0,
        "version": 1,
    }


def _load_state(context) -> dict[str, Any] | None:
    raw = context.state.get("chess")
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != 1 or not isinstance(raw.get("board"), list) or len(raw["board"]) != 64:
        return None
    if raw.get("turn") not in {"w", "b"}:
        return None
    return raw


def _pseudo_moves(
    board: list[dict[str, str] | None],
    color: str,
    en_passant: str,
    castling: dict[str, bool] | None = None,
    *,
    include_castling: bool = True,
) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    for index, piece in enumerate(board):
        if not piece or _color(piece) != color:
            continue
        file, rank = _file_rank(index)
        kind = _kind(piece)
        if kind == "P":
            direction = 1 if color == "w" else -1
            start_rank = 1 if color == "w" else 6
            promotion_rank = 7 if color == "w" else 0
            one = _idx(file, rank + direction) if _inside(file, rank + direction) else None
            if one is not None and board[one] is None:
                if rank + direction == promotion_rank:
                    for promotion in ("q", "r", "b", "n"):
                        moves.append({"from": index, "to": one, "promotion": promotion, "castle": None, "en_passant": False})
                else:
                    moves.append({"from": index, "to": one, "promotion": None, "castle": None, "en_passant": False})
                if rank == start_rank:
                    two = _idx(file, rank + 2 * direction)
                    if board[two] is None:
                        moves.append({"from": index, "to": two, "promotion": None, "castle": None, "en_passant": False})
            for df in (-1, 1):
                target_file = file + df
                target_rank = rank + direction
                if not _inside(target_file, target_rank):
                    continue
                target = _idx(target_file, target_rank)
                enemy = board[target]
                if enemy and _color(enemy) != color:
                    if target_rank == promotion_rank:
                        for promotion in ("q", "r", "b", "n"):
                            moves.append({"from": index, "to": target, "promotion": promotion, "castle": None, "en_passant": False})
                    else:
                        moves.append({"from": index, "to": target, "promotion": None, "castle": None, "en_passant": False})
                elif en_passant and _square(target) == en_passant:
                    moves.append({"from": index, "to": target, "promotion": None, "castle": None, "en_passant": True})
        elif kind == "N":
            for df, dr in KNIGHT_DELTAS:
                if _inside(file + df, rank + dr):
                    target = _idx(file + df, rank + dr)
                    if not board[target] or _color(board[target]) != color:
                        moves.append({"from": index, "to": target, "promotion": None, "castle": None, "en_passant": False})
        elif kind in SLIDING_DIRECTIONS:
            for df, dr in SLIDING_DIRECTIONS[kind]:
                nf, nr = file + df, rank + dr
                while _inside(nf, nr):
                    target = _idx(nf, nr)
                    occupant = board[target]
                    if not occupant:
                        moves.append({"from": index, "to": target, "promotion": None, "castle": None, "en_passant": False})
                    else:
                        if _color(occupant) != color:
                            moves.append({"from": index, "to": target, "promotion": None, "castle": None, "en_passant": False})
                        break
                    nf += df
                    nr += dr
        elif kind == "K":
            for df, dr in KING_DELTAS:
                if _inside(file + df, rank + dr):
                    target = _idx(file + df, rank + dr)
                    if not board[target] or _color(board[target]) != color:
                        moves.append({"from": index, "to": target, "promotion": None, "castle": None, "en_passant": False})
            if include_castling:
                moves.extend(_castling_moves(board, color, index, castling or {}))
    return moves


def _castling_moves(
    board: list[dict[str, str] | None],
    color: str,
    king_index: int,
    castling: dict[str, bool],
) -> list[dict[str, Any]]:
    rank = 0 if color == "w" else 7
    home = _idx(4, rank)
    if king_index != home or _kind(board[home]) != "K" or _is_attacked(board, home, _opponent(color)):
        return []
    enemy = _opponent(color)
    moves: list[dict[str, Any]] = []
    if castling.get(f"{color}K") and board[_idx(7, rank)] and _kind(board[_idx(7, rank)]) == "R" and _color(board[_idx(7, rank)]) == color:
        if not board[_idx(5, rank)] and not board[_idx(6, rank)]:
            if not _is_attacked(board, _idx(5, rank), enemy) and not _is_attacked(board, _idx(6, rank), enemy):
                moves.append({
                    "from": king_index,
                    "to": _idx(6, rank),
                    "promotion": None,
                    "castle": "K" if color == "w" else "k",
                    "en_passant": False,
                })
    if castling.get(f"{color}Q") and board[_idx(0, rank)] and _kind(board[_idx(0, rank)]) == "R" and _color(board[_idx(0, rank)]) == color:
        if not board[_idx(1, rank)] and not board[_idx(2, rank)] and not board[_idx(3, rank)]:
            if not _is_attacked(board, _idx(3, rank), enemy) and not _is_attacked(board, _idx(2, rank), enemy):
                moves.append({
                    "from": king_index,
                    "to": _idx(2, rank),
                    "promotion": None,
                    "castle": "Q" if color == "w" else "q",
                    "en_passant": False,
                })
    return moves


def _attack_squares(
    board: list[dict[str, str] | None],
    color: str,
    en_passant: str = "",
) -> set[int]:
    attacked: set[int] = set()
    for index, piece in enumerate(board):
        if not piece or _color(piece) != color:
            continue
        file, rank = _file_rank(index)
        kind = _kind(piece)
        if kind == "P":
            direction = 1 if color == "w" else -1
            for df in (-1, 1):
                if not _inside(file + df, rank + direction):
                    continue
                target = _idx(file + df, rank + direction)
                attacked.add(target)
                if en_passant and _square(target) == en_passant:
                    attacked.add(target + (8 if color == "w" else -8))
        elif kind == "N":
            for df, dr in KNIGHT_DELTAS:
                if _inside(file + df, rank + dr):
                    attacked.add(_idx(file + df, rank + dr))
        elif kind in SLIDING_DIRECTIONS:
            for df, dr in SLIDING_DIRECTIONS[kind]:
                nf, nr = file + df, rank + dr
                while _inside(nf, nr):
                    target = _idx(nf, nr)
                    attacked.add(target)
                    if board[target]:
                        break
                    nf += df
                    nr += dr
        elif kind == "K":
            for df, dr in KING_DELTAS:
                if _inside(file + df, rank + dr):
                    attacked.add(_idx(file + df, rank + dr))
    return attacked


def _is_attacked(
    board: list[dict[str, str] | None],
    target: int,
    by_color: str,
) -> bool:
    return target in _attack_squares(board, by_color)


def _king_index(board: list[dict[str, str] | None], color: str) -> int | None:
    for index, piece in enumerate(board):
        if piece and piece["code"] == f"{color}K":
            return index
    return None


def _apply_move(
    board: list[dict[str, str] | None],
    state: dict[str, Any],
    move: dict[str, Any],
) -> tuple[list[dict[str, str] | None], dict[str, Any]]:
    next_board = [None if piece is None else dict(piece) for piece in board]
    next_state = {
        **state,
        "board": next_board,
        "castling": dict(state["castling"]),
        "last_move": {"from": _square(move["from"]), "to": _square(move["to"])},
        "move_number": int(state.get("move_number", 0)) + 1,
    }
    piece = next_board[move["from"]]
    if piece is None:
        return next_board, next_state
    color = _color(piece)
    moving_kind = _kind(piece)
    captured = next_board[move["to"]]
    captured_code = _kind(captured)
    if move["en_passant"]:
        captured_idx = move["to"] + (8 if color == "w" else -8)
        captured = next_board[captured_idx]
        captured_code = _kind(captured)
        next_board[captured_idx] = None
    next_board[move["to"]] = piece
    next_board[move["from"]] = None
    if move["promotion"]:
        piece["code"] = f"{color}{move['promotion'].upper()}"
    if move["castle"]:
        rank = 0 if color == "w" else 7
        if move["castle"].lower() == "k":
            rook_from, rook_to = _idx(7, rank), _idx(5, rank)
        else:
            rook_from, rook_to = _idx(0, rank), _idx(3, rank)
        next_board[rook_to] = next_board[rook_from]
        next_board[rook_from] = None
    rights = next_state["castling"]
    if moving_kind == "K":
        rights[f"{color}K"] = False
        rights[f"{color}Q"] = False
    if moving_kind == "R":
        from_file, from_rank = _file_rank(move["from"])
        if from_rank in (0, 7) and from_file in (0, 7):
            side = "K" if from_file == 7 else "Q"
            rights[f"{color}{side}"] = False
    if captured_code == "R" and captured is not None:
        target_file, target_rank = _file_rank(move["to"])
        if target_rank in (0, 7) and target_file in (0, 7):
            side = "K" if target_file == 7 else "Q"
            rights[f"{_opponent(color)}{side}"] = False
    next_state["en_passant"] = ""
    if moving_kind == "P" and abs(move["to"] - move["from"]) == 16:
        next_state["en_passant"] = _square((move["from"] + move["to"]) // 2)
    next_state["halfmove"] = 0 if moving_kind == "P" or captured_code else int(state.get("halfmove", 0)) + 1
    next_state["turn"] = _opponent(color)
    if color == "b":
        next_state["fullmove"] = int(state.get("fullmove", 1)) + 1
    return next_board, next_state


def _legal_moves(
    board: list[dict[str, str] | None],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    color = state["turn"]
    legal: list[dict[str, Any]] = []
    for move in _pseudo_moves(board, color, state.get("en_passant", ""), state.get("castling")):
        next_board, _ = _apply_move(board, state, move)
        king = _king_index(next_board, color)
        if king is not None and _is_attacked(next_board, king, _opponent(color)):
            continue
        legal.append(move)
    return legal


def _insufficient_material(board: list[dict[str, str] | None]) -> bool:
    pieces = [(index, piece) for index, piece in enumerate(board) if piece]
    if len(pieces) == 2:
        return True
    if len(pieces) == 3:
        return any(_kind(piece) in {"B", "N"} for _, piece in pieces)
    if len(pieces) == 4:
        bishops = [(index, piece) for index, piece in pieces if _kind(piece) == "B"]
        if len(bishops) == 2:
            colors = {_color(piece) for _, piece in pieces}
            squares = {(index % 8 + (7 - index // 8)) % 2 for index, _ in bishops}
            return len(colors) == 2 and len(squares) == 1
    return False


def _hazards(
    board: list[dict[str, str] | None],
    state: dict[str, Any],
) -> dict[str, str]:
    """Return square -> effect set for pieces attacked by an enemy and checks."""

    hazards: dict[str, str] = {}
    for color in ("w", "b"):
        enemy = _opponent(color)
        attacked = _attack_squares(board, enemy, state.get("en_passant", ""))
        for index, piece in enumerate(board):
            if piece and _color(piece) == color and index in attacked:
                hazards[_square(index)] = "threat"
    for color in ("w", "b"):
        king = _king_index(board, color)
        if king is not None and _is_attacked(board, king, _opponent(color)):
            hazards[_square(king)] = "check"
    return hazards


def _status(
    board: list[dict[str, str] | None],
    state: dict[str, Any],
    legal: list[dict[str, Any]],
) -> tuple[str, str]:
    turn = state["turn"]
    label = "White" if turn == "w" else "Black"
    other = "Black" if turn == "w" else "White"
    king = _king_index(board, turn)
    in_check = king is not None and _is_attacked(board, king, _opponent(turn))
    if not legal:
        if in_check:
            return f"Checkmate — {other} wins", _opponent(turn)
        return "Stalemate — draw", "draw"
    if _insufficient_material(board):
        return "Draw — insufficient material", "draw"
    move_number = int(state.get("move_number", 0))
    suffix = f" · {move_number}/{MOVE_LIMIT}"
    return f"{label} to move" + (" — check" if in_check else "") + suffix, ""


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    board = state["board"]
    legal = _legal_moves(board, state)
    status, winner = _status(board, state, legal)
    targets: dict[str, list[str]] = {}
    for move in legal:
        source = _square(move["from"])
        destination = _square(move["to"])
        bucket = targets.setdefault(source, [])
        if destination not in bucket:
            bucket.append(destination)
    pieces = [
        {"id": piece["id"], "code": piece["code"], "square": _square(index)}
        for index, piece in enumerate(board)
        if piece is not None
    ]
    return {
        "pieces": pieces,
        "moves": targets,
        "hazards": _hazards(board, state),
        "turn": state["turn"],
        "status": status,
        "winner": winner,
        "last_move": state.get("last_move"),
        "move_number": int(state.get("move_number", 0)),
        "move_limit": MOVE_LIMIT,
    }


def _publish(context, state: dict[str, Any]) -> None:
    context.state["chess"] = state
    context.set_game_state(_public_state(state))


def _reset_powers(context) -> tuple[str, ...]:
    room = getattr(context, "room", None)
    game = room.get("game") if isinstance(room, dict) else None
    values = game.get("reset_powers") if isinstance(game, dict) else None
    if isinstance(values, list):
        return tuple(str(value) for value in values)
    return RESET_POWERS


def _can_reset(context) -> bool:
    return any(context.has_power(power) for power in _reset_powers(context))


def _parse_move(action: str) -> tuple[str, str, str] | None:
    if not action.startswith("move:"):
        return None
    token = action[5:]
    if len(token) not in {4, 5}:
        return None
    source, target = token[:2], token[2:4]
    promotion = token[4:5] or ""
    if not all(square[0] in FILES and square[1] in "12345678" for square in (source, target)):
        return None
    if promotion and promotion not in {"q", "r", "b", "n"}:
        return None
    return source, target, promotion


def _give_rewards(
    context,
    *,
    state: dict[str, Any],
    captured_code: str,
    winner: str,
    mover: str,
) -> None:
    move_number = int(state.get("move_number", 0))
    game_key = str(state.get("started_at", ""))
    if captured_code:
        value = PIECE_VALUES.get(captured_code, 0)
        if value:
            context.grant(
                bops=value,
                ledger_key=f"chess:{game_key}:capture:{move_number}",
            )
            context.effect("sparks")
            context.feedback(f"Capture! +{value} Bops.", "success")
    if winner and winner != "draw" and winner == mover:
        context.grant(
            kudos=WIN_KUDOS,
            ledger_key=f"chess:{game_key}:win:{move_number}",
        )
        context.effect("fire")
        context.feedback(f"Checkmate! +{WIN_KUDOS} Kudos.", "success")


def on_enter(context, event):
    """Initialize the board when the first visitor arrives, or refresh stale clients."""

    del event
    state = _load_state(context)
    if state is None:
        state = _initial_state(context)
    _publish(context, state)


def on_tick(context, event):
    """Initialize a board that was persisted before a restart but never published."""

    del event
    if _load_state(context) is None:
        _publish(context, _initial_state(context))


def on_quick_action(context, event):
    """Apply a move or staff reset sent through ``.act <action> @prop:<board>``."""

    action = str(event.action or "").strip().lower()
    state = _load_state(context)
    if state is None:
        state = _initial_state(context)
    if action == "reset":
        if not _can_reset(context):
            context.feedback("Only an admin, moderator, or game master can reset the chess board.", "error")
            return
        _publish(context, _initial_state(context))
        context.feedback("Chess board reset. White to move.", "success")
        return
    parsed = _parse_move(action)
    if parsed is None:
        context.feedback("Use the board to select a piece and a square.", "error")
        return
    source, target, promotion = parsed
    legal = _legal_moves(state["board"], state)
    candidates = [
        move for move in legal
        if _square(move["from"]) == source and _square(move["to"]) == target
    ]
    if not candidates:
        context.feedback("That move is not legal.", "error")
        return
    if promotion:
        candidates = [move for move in candidates if move["promotion"] == promotion]
        if not candidates:
            context.feedback("That promotion is not legal.", "error")
            return
    else:
        promoted = [move for move in candidates if move["promotion"]]
        candidates = [move for move in promoted if move["promotion"] == "q"] or candidates
    move = candidates[0]
    if context.counter("energy") < MOVE_ENERGY_COST:
        context.feedback(f"Not enough Energy to move (needs {MOVE_ENERGY_COST}).", "error")
        return
    piece = state["board"][move["from"]]
    mover = _color(piece)
    captured_code = _kind(state["board"][move["to"]])
    if move["en_passant"]:
        captured_index = move["to"] + (8 if mover == "w" else -8)
        captured_code = _kind(state["board"][captured_index])
    next_board, next_state = _apply_move(state["board"], state, move)
    context.apply_counter("energy", -MOVE_ENERGY_COST)
    public = _public_state(next_state)
    limit_reached = int(next_state.get("move_number", 0)) >= MOVE_LIMIT
    _publish(context, _initial_state(context) if limit_reached else next_state)
    _give_rewards(
        context,
        state=next_state,
        captured_code=captured_code,
        winner=public["winner"],
        mover=mover,
    )
    if limit_reached:
        context.feedback(f"{MOVE_LIMIT}-move limit reached. The chess board resets.", "info")
    if public["winner"] == "draw":
        context.feedback(public["status"], "info")
    elif public["winner"] and public["winner"] == mover:
        context.feedback(public["status"], "success")
