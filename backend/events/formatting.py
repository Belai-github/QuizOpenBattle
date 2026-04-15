def _team_label(team: str):
    if team == "team-left":
        return "先攻"
    if team == "team-right":
        return "後攻"
    return ""


def format_turn_changed_message(next_turn_team: str | None):
    next_label = _team_label(str(next_turn_team or ""))
    if next_label == "":
        return "ターン終了。"
    return f"ターン終了。{next_label}のターンになりました。"


def format_open_vote_request_message(requester_name: str, char_index: int, should_emit_vote_log: bool):
    if should_emit_vote_log:
        return f"{requester_name} が {char_index + 1}文字目のオープン投票を開始しました。"
    return f"{requester_name} が {char_index + 1}文字目をオープンしました。"


def format_open_vote_resolution_message(team_label: str, char_index: int, approved: bool):
    if approved:
        return f"{team_label}が{char_index + 1}文字目をオープンしました。"
    return f"{team_label}が{char_index + 1}文字目をオープンできませんでした。"


def format_answer_attempt_message(team_label: str, answer_text: str):
    return f"{team_label}が「{answer_text}」とアンサーしました。"


def format_answer_vote_request_message(requester_name: str, answer_text: str, should_emit_vote_log: bool):
    if should_emit_vote_log:
        return f"{requester_name} が「{answer_text}」とアンサーしました。"
    return f"{requester_name} が「{answer_text}」とアンサーしました。"


def format_answer_vote_resolution_message(team_label: str, answer_text: str, approved: bool, should_emit_vote_log: bool):
    if approved:
        return f"{team_label}が「{answer_text}」とアンサーしました。"
    if should_emit_vote_log:
        return "アンサー投票否決"
    return f"{team_label}の解答送信に失敗しました。"


def format_turn_end_vote_request_message(requester_name: str, should_emit_vote_log: bool):
    if should_emit_vote_log:
        return f"{requester_name} がターンエンド投票を開始しました。"
    return f"{requester_name} がターンエンドしました。"


def format_turn_end_vote_resolution_message(approved: bool):
    return "ターンエンド投票可決" if approved else "ターンエンド投票否決"


def format_intentional_draw_vote_resolution_message(approved: bool):
    return "フルオープン決着が成立しました。" if approved else "フルオープン決着は否決されました。"


def format_answer_result_message(team_label: str, is_correct: bool):
    result_label = "正解" if is_correct else "誤答"
    return f"{team_label}の解答は{result_label}でした。"


def format_game_finished_message(winner: str | None):
    if winner == "team-left":
        return "ゲーム終了！先攻の勝利"
    elif winner == "team-right":
        return "ゲーム終了！後攻の勝利"
    else:
        return "ゲーム終了！引き分け"
