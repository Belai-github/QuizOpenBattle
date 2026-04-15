let ws;
let myClientId = null;

const confirmModal = document.getElementById("confirm-modal");
const confirmMessageEl = document.getElementById("confirm-message");
const confirmOkBtn = document.getElementById("confirm-ok-btn");
const confirmCancelBtn = document.getElementById("confirm-cancel-btn");
const confirmActionsEl = confirmModal.querySelector(".modal-actions");
const alertModal = document.getElementById("alert-modal");
const alertMessageEl = document.getElementById("alert-message");
const alertOkBtn = document.getElementById("alert-ok-btn");
const leaveGameArenaEl = document.getElementById("leave-game-arena");
const startGameBtnEl = document.getElementById("start-game-btn");
const shuffleParticipantsBtnEl = document.getElementById("shuffle-participants-btn");
const toggleQuestionVisibilityBtnEl = document.getElementById("toggle-question-visibility-btn");
const arenaAnswerBoxEl = document.getElementById("arena-answer-box");
const arenaAnswerInputEl = document.getElementById("arena-answer-input");
const arenaAnswerSubmitBtnEl = document.getElementById("arena-answer-submit-btn");
const arenaTurnEndBtnEl = document.getElementById("arena-turn-end-btn");
const rulebookTriggerEls = document.querySelectorAll(".rulebook-trigger");
const rulebookModalEl = document.getElementById("rulebook-modal");
const rulebookContentEl = document.getElementById("rulebook-content");
const rulebookCloseBtnEl = document.getElementById("rulebook-close-btn");

let pendingArenaMode = null;
let userRole = null; // "questioner", "team-left", "team-right", "spectator", null
let currentRoomGameState = null; // "waiting" | "playing" | "finished" | null
let currentGameState = null; // game中の詳細状態: {current_turn_team, team_left: {...}, team_right: {...}, ...}
let currentRoomSnapshot = null;
const handledOpenVoteIds = new Set();
const handledAnswerVoteIds = new Set();
const handledTurnEndVoteIds = new Set();
let openVoteRequestPending = false;
let turnEndRequestPending = false;
const CHAT_MAX_LENGTH = 200;
const CHAT_MIN_INTERVAL_MS = 800;
const ARENA_MASK_CHAR = "■";
const ARENA_MIN_CHARS_PER_LINE = 4;
const QUESTIONER_VIEW_MODE_CYCLE = ["all", "team-left", "team-right"];
const SPECTATOR_VIEW_MODE_CYCLE = ["team-left", "team-right"];
const DEBUG_VIEWPORT_OVERLAY_ENABLED = true;
let currentArenaQuestionRawText = "";
let questionerViewMode = "all";
const selectedArenaQuestionCharIndexes = new Set();
let lastAutoSelectedQuestionKey = null;
const lastChatSentAt = {}; // key: "lobby" or "game-all", "team-left", "team-right", "questioner"
let lastRulebookTriggerEl = null;
let viewportDebugEl = null;
let previousRoomGameState = null;

function setArenaCharClickGuard() {
    // No-op: モーダル閉鎖後の1クリック破棄はUXを損なうため廃止。
}

function isAnyModalOpen() {
    const judgementModal = document.getElementById("answer-judgement-modal");
    if (confirmModal && !confirmModal.classList.contains("hidden")) return true;
    if (alertModal && !alertModal.classList.contains("hidden")) return true;
    if (rulebookModalEl && !rulebookModalEl.classList.contains("hidden")) return true;
    if (judgementModal && !judgementModal.classList.contains("hidden")) return true;
    return false;
}

function updateArenaInteractionLock() {
    document.body.classList.toggle("modal-open", isAnyModalOpen());
}

function shouldSuppressArenaCharClick() {
    return isAnyModalOpen();
}

function removeWhitespaceTextNodes(rootEl) {
    if (!rootEl) return;

    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT);
    const nodesToRemove = [];

    while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.nodeValue || node.nodeValue.trim() !== "") continue;
        nodesToRemove.push(node);
    }

    nodesToRemove.forEach((node) => {
        node.parentNode?.removeChild(node);
    });
}

function ensureViewportDebugOverlay() {
    if (!DEBUG_VIEWPORT_OVERLAY_ENABLED) return null;
    if (viewportDebugEl) return viewportDebugEl;

    const el = document.createElement("div");
    el.id = "viewport-debug";
    el.setAttribute("aria-hidden", "true");
    document.body.appendChild(el);
    viewportDebugEl = el;
    return viewportDebugEl;
}

function updateViewportDebugOverlay() {
    if (!DEBUG_VIEWPORT_OVERLAY_ENABLED) return;
    const el = ensureViewportDebugOverlay();
    if (!el) return;

    const viewportWidth = Math.round(window.innerWidth);
    el.textContent = `W: ${viewportWidth}px`;
}

function updateChatBoxVisibility() {
    updateArenaLogElementVisibility();

    document.querySelectorAll(".chat-box").forEach((chatBox) => {
        const visibility = chatBox.getAttribute("data-visibility");
        const chatRoom = chatBox.getAttribute("data-chat-room");
        const chatType = chatBox.getAttribute("data-chat-type") || "lobby";

        // チャットルームが異なれば非表示
        if (chatRoom === "game" && !isInGameArena()) {
            chatBox.classList.add("hidden");
            return;
        }
        if (chatRoom === "lobby" && isInGameArena()) {
            chatBox.classList.add("hidden");
            return;
        }

        // アリーナ内チャットはゲーム状態で出し分ける。
        if (chatRoom === "game") {
            const roomState = currentRoomGameState || "waiting";
            const isGlobalChat = chatType === "game-global";

            if (roomState === "waiting") {
                if (!isGlobalChat) {
                    setChatBoxEditable(chatBox, false);
                    chatBox.classList.add("hidden");
                    return;
                }

                chatBox.classList.remove("hidden");
                setChatBoxEditable(chatBox, true);
                return;
            }

            if (roomState === "playing" && isGlobalChat) {
                setChatBoxEditable(chatBox, false);
                chatBox.classList.add("hidden");
                return;
            }
        }

        // visibility属性がなければ誰でも見れる
        if (!visibility) {
            chatBox.classList.remove("hidden");
            setChatBoxEditable(chatBox, canSendChatType(chatType));
            return;
        }

        // visibility属性があれば権限チェック
        const canView = canViewChatBox(visibility);
        chatBox.classList.toggle("hidden", !canView);
        if (canView) {
            setChatBoxEditable(chatBox, canSendChatType(chatType));
        }
    });

    syncArenaPlayerBoxHeights();
}

function updateArenaLogElementVisibility() {
    const roomState = currentRoomGameState || "waiting";
    const splitLogIds = ["game-chat-log-team-left", "game-chat-log-team-right"];

    splitLogIds.forEach((id) => {
        const logEl = document.getElementById(id);
        if (!logEl) return;
        logEl.classList.toggle("hidden", roomState === "waiting");
    });

    const splitTitleSelectors = [
        '.chat-box[data-chat-room="game"][data-chat-type="team-left"] .arena-chat-title',
        '.chat-box[data-chat-room="game"][data-chat-type="team-right"] .arena-chat-title',
    ];
    splitTitleSelectors.forEach((selector) => {
        const titleEl = document.querySelector(selector);
        if (!titleEl) return;
        titleEl.classList.toggle("hidden", roomState === "waiting");
    });
}

function syncArenaPlayerBoxHeights() {
    const leftBoxEl = document.getElementById("arena-player-left");
    const rightBoxEl = document.getElementById("arena-player-right");
    const questionBoxEl = document.getElementById("arena-question-board");
    if (!leftBoxEl || !rightBoxEl || !questionBoxEl) return;

    leftBoxEl.style.minHeight = "";
    rightBoxEl.style.minHeight = "";
    questionBoxEl.style.minHeight = "";

    if (!isInGameArena()) return;
    if (!window.matchMedia("(min-width: 768px)").matches) return;

    // 問題文が長い場合でも左右の参加者ボックスが追従するようにする。
    const targetHeight = Math.max(
        questionBoxEl.offsetHeight,
        leftBoxEl.offsetHeight,
        rightBoxEl.offsetHeight,
    );
    leftBoxEl.style.minHeight = `${targetHeight}px`;
    rightBoxEl.style.minHeight = `${targetHeight}px`;
    questionBoxEl.style.minHeight = `${targetHeight}px`;
}

function setChatBoxEditable(chatBoxEl, editable) {
    const inputEl = chatBoxEl.querySelector(".chat-input");
    const sendBtnEl = chatBoxEl.querySelector(".chat-send-btn");
    const composeEl = chatBoxEl.querySelector(".chat-compose");

    chatBoxEl.classList.toggle("read-only", !editable);

    if (composeEl) {
        composeEl.classList.toggle("hidden", !editable);
    }

    if (inputEl) {
        inputEl.disabled = !editable;
        inputEl.setAttribute("aria-disabled", String(!editable));
    }

    if (sendBtnEl) {
        sendBtnEl.disabled = !editable;
        sendBtnEl.setAttribute("aria-disabled", String(!editable));
    }
}

function canSendChatType(chatType) {
    if (chatType === "lobby") {
        return true;
    }

    // 準備中はアリーナ内の全体チャットのみ全員が送信できる。
    if (chatType === "game-global" && (currentRoomGameState || "waiting") === "waiting") {
        return true;
    }

    const sendableRolesByType = {
        "team-left": new Set(["team-left", "questioner"]),
        "team-right": new Set(["team-right", "questioner"]),
        spectator: new Set(["spectator", "questioner"]),
    };

    const allowedRoles = sendableRolesByType[chatType];
    if (!allowedRoles) {
        return false;
    }

    return allowedRoles.has(userRole);
}

function canViewChatBox(visibility) {
    if (!visibility) return true;

    // 複数の権限が指定される場合に対応 (例: "team-left,questioner")
    const visibilities = visibility.split(",").map((v) => v.trim());
    return visibilities.includes(userRole);
}

function isInGameArena() {
    return document.getElementById("game-arena-screen").style.display !== "none";
}

function canSelectArenaQuestionChars() {
    const roomState = currentRoomGameState || "waiting";
    return isInGameArena() && userRole === "questioner" && roomState === "waiting";
}

function isAnswerJudgementPending() {
    return Boolean(currentGameState?.is_judging_answer);
}

function canRequestOpenCharacter() {
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;
    if (userRole !== "team-left" && userRole !== "team-right") return false;
    return currentGameState?.current_turn_team === userRole;
}

function canSubmitArenaAnswer() {
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;
    if (userRole !== "team-left" && userRole !== "team-right") return false;
    return currentGameState?.current_turn_team === userRole;
}

function canRequestTurnEnd() {
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;
    if (userRole !== "team-left" && userRole !== "team-right") return false;
    return currentGameState?.current_turn_team === userRole;
}

function getCurrentTeamActionPoints() {
    if (userRole === "team-left") {
        const state = currentGameState?.team_left || {};
        return state.action_points || 0;
    }

    if (userRole === "team-right") {
        const state = currentGameState?.team_right || {};
        return state.action_points || 0;
    }

    return 0;
}

function canViewArenaAnswerForm() {
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    return userRole === "team-left" || userRole === "team-right";
}

function getCurrentTeamParticipantCount() {
    if (!currentRoomSnapshot) {
        return 1;
    }

    if (userRole === "team-left") {
        return Array.isArray(currentRoomSnapshot.left_participants)
            ? currentRoomSnapshot.left_participants.length
            : 1;
    }

    if (userRole === "team-right") {
        return Array.isArray(currentRoomSnapshot.right_participants)
            ? currentRoomSnapshot.right_participants.length
            : 1;
    }

    return 1;
}

function updateArenaAnswerFormVisibility() {
    if (!arenaAnswerBoxEl || !arenaAnswerInputEl || !arenaAnswerSubmitBtnEl || !arenaTurnEndBtnEl) return;

    const canView = canViewArenaAnswerForm();
    const canSubmit = canSubmitArenaAnswer();
    const canEndTurn = canRequestTurnEnd();
    const teamParticipantCount = getCurrentTeamParticipantCount();
    const isProposalMode = teamParticipantCount > 1;
    arenaAnswerBoxEl.classList.toggle("hidden", !canView);
    arenaAnswerInputEl.disabled = !canSubmit;
    arenaAnswerSubmitBtnEl.disabled = !canSubmit;
    arenaTurnEndBtnEl.disabled = !canEndTurn;
    arenaAnswerSubmitBtnEl.textContent = isProposalMode ? "解答提案" : "解答";
    arenaAnswerSubmitBtnEl.setAttribute("aria-label", isProposalMode ? "解答提案" : "解答送信");

    if (!canView) {
        arenaAnswerInputEl.value = "";
    }
}

async function submitTurnEndAttempt() {
    if (!canRequestTurnEnd()) return;

    if (turnEndRequestPending) {
        await showAlertModal("ターンエンド処理中です。少し待ってください。");
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const teamParticipantCount = getCurrentTeamParticipantCount();
    const isProposalMode = teamParticipantCount > 1;
    const hasRemainingActions = getCurrentTeamActionPoints() > 0;
    const warning = hasRemainingActions
        ? "\n\nアクション権が残っています。本当にターンエンドしますか？"
        : "";
    const confirmed = await showConfirmModal(
        isProposalMode
            ? `ターンエンドを提案しますか？${warning}`
            : `ターンエンドしますか？${warning}`,
        {
            okLabel: isProposalMode ? "提案する" : "ターンエンドする",
            cancelLabel: "キャンセル",
        }
    );
    if (!confirmed) {
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    turnEndRequestPending = true;
    ws.send(
        JSON.stringify({
            type: "turn_end_attempt",
            timestamp: Date.now(),
        })
    );

    window.setTimeout(() => {
        turnEndRequestPending = false;
    }, 800);
}

async function submitArenaAnswer() {
    if (!arenaAnswerInputEl) return;
    if (!canSubmitArenaAnswer()) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const answerText = arenaAnswerInputEl.value.trim();
    if (answerText === "") {
        await showAlertModal("解答を入力してください");
        return;
    }

    const teamParticipantCount = getCurrentTeamParticipantCount();
    const isProposalMode = teamParticipantCount > 1;
    const confirmMessage = isProposalMode
        ? `この内容で解答を提案しますか？\n\n${answerText}`
        : `この内容で解答を送信しますか？\n\n${answerText}`;
    const okLabel = isProposalMode ? "提案する" : "送信する";

    const confirmed = await showConfirmModal(
        confirmMessage,
        {
            okLabel,
            cancelLabel: "キャンセル",
        }
    );
    if (!confirmed) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "answer_attempt",
            answer_text: answerText,
            timestamp: Date.now(),
        })
    );

    arenaAnswerInputEl.value = "";
}

function updateChatLengthWarning(inputEl) {
    if (!inputEl) return;

    const warningEl = inputEl.closest(".chat-box")?.querySelector(".chat-length-warning");
    if (!warningEl) return;

    const reachedLimit = inputEl.value.length >= CHAT_MAX_LENGTH;
    warningEl.classList.toggle("hidden", !reachedLimit);
}

function updateArenaLeaveLabel(mode) {
    if (!leaveGameArenaEl) return;

    if (mode === "owner") {
        leaveGameArenaEl.textContent = "✕ 部屋を閉じる";
        leaveGameArenaEl.setAttribute("aria-label", "部屋を閉じる");
        return;
    }

    leaveGameArenaEl.textContent = "←退室";
    leaveGameArenaEl.setAttribute("aria-label", "退室");
}

function updateGameStateUI() {
    // waiting -> playing へ遷移したタイミングで、出題前の選択状態を確実に破棄する
    if (previousRoomGameState !== "playing" && currentRoomGameState === "playing") {
        selectedArenaQuestionCharIndexes.clear();
        lastAutoSelectedQuestionKey = null;
    }
    previousRoomGameState = currentRoomGameState;

    if (!currentGameState || currentRoomGameState !== "playing") {
        // ゲーム中でない場合はアクション権表示をリセット・非表示
        const leftDisplay = document.getElementById("arena-action-points-left");
        const rightDisplay = document.getElementById("arena-action-points-right");
        if (leftDisplay) {
            leftDisplay.classList.add("arena-action-points-hidden");
            leftDisplay.querySelector(".action-count").textContent = "0";
            leftDisplay.querySelector(".bonus-count").textContent = "0";
        }
        if (rightDisplay) {
            rightDisplay.classList.add("arena-action-points-hidden");
            rightDisplay.querySelector(".action-count").textContent = "0";
            rightDisplay.querySelector(".bonus-count").textContent = "0";
        }

        // ターン表示をリセット
        const leftBox = document.getElementById("arena-player-left");
        const rightBox = document.getElementById("arena-player-right");
        if (leftBox) leftBox.classList.remove("is-current-turn");
        if (rightBox) rightBox.classList.remove("is-current-turn");
        return;
    }

    // アクション権表示を更新
    const leftTeamState = currentGameState.team_left || {};
    const rightTeamState = currentGameState.team_right || {};
    const currentTurn = currentGameState.current_turn_team;

    // 先攻（左）のアクション権
    const leftDisplay = document.getElementById("arena-action-points-left");
    if (leftDisplay) {
        leftDisplay.classList.remove("arena-action-points-hidden");
        leftDisplay.querySelector(".action-count").textContent = leftTeamState.action_points || 0;
        leftDisplay.querySelector(".bonus-count").textContent = leftTeamState.bonus_action_points || 0;
    }

    // 後攻（右）のアクション権
    const rightDisplay = document.getElementById("arena-action-points-right");
    if (rightDisplay) {
        rightDisplay.classList.remove("arena-action-points-hidden");
        rightDisplay.querySelector(".action-count").textContent = rightTeamState.action_points || 0;
        rightDisplay.querySelector(".bonus-count").textContent = rightTeamState.bonus_action_points || 0;
    }

    // ターン表示（ボックスを光らせる）
    const leftBox = document.getElementById("arena-player-left");
    const rightBox = document.getElementById("arena-player-right");
    if (leftBox) {
        leftBox.classList.toggle("is-current-turn", currentTurn === "team-left");
    }
    if (rightBox) {
        rightBox.classList.toggle("is-current-turn", currentTurn === "team-right");
    }
}

function showWaitingRoomScreen() {
    document.getElementById("waiting-room-screen").style.display = "block";
    document.getElementById("game-arena-screen").style.display = "none";
    updateStartGameButtonVisibility(null);
    updateQuestionVisibilityButton();
    updateArenaAnswerFormVisibility();
    updateChatBoxVisibility();
}

function showGameArenaScreen() {
    const wasInGameArena = isInGameArena();
    document.getElementById("waiting-room-screen").style.display = "none";
    document.getElementById("game-arena-screen").style.display = "block";

    // 出題者は部屋に入った直後のみ、全開示表示を初期状態にする。
    if (!wasInGameArena && userRole === "questioner") {
        questionerViewMode = "all";
    }

    updateQuestionVisibilityButton();
    updateArenaAnswerFormVisibility();
    updateChatBoxVisibility();
}

function isGameFinished() {
    return currentRoomGameState === "finished"
        || (currentRoomGameState === "playing" && currentGameState?.game_status === "finished");
}

function canToggleQuestionViewMode() {
    if (!isInGameArena()) {
        return false;
    }

    if (userRole === "questioner") {
        return true;
    }

    const roomState = currentRoomGameState || "waiting";
    const isFinished = isGameFinished();

    // 対戦終了状態では参加者も切り替え可能
    if (isFinished && (userRole === "team-left" || userRole === "team-right")) {
        return true;
    }

    return userRole === "spectator" && roomState === "playing";
}

function getQuestionViewModeCycleForCurrentUser() {
    if (userRole === "questioner") {
        return QUESTIONER_VIEW_MODE_CYCLE;
    }
    // 対戦終了状態では参加者もQUESTIONER_VIEW_MODE_CYCLE を使う
    if (isGameFinished() && (userRole === "team-left" || userRole === "team-right")) {
        return QUESTIONER_VIEW_MODE_CYCLE;
    }
    if (userRole === "spectator") {
        return SPECTATOR_VIEW_MODE_CYCLE;
    }
    return QUESTIONER_VIEW_MODE_CYCLE;
}


function updateQuestionVisibilityButton() {
    if (!toggleQuestionVisibilityBtnEl) return;

    const canToggle = canToggleQuestionViewMode() && !isAnswerJudgementPending();
    toggleQuestionVisibilityBtnEl.classList.toggle("hidden", !canToggle);
    toggleQuestionVisibilityBtnEl.disabled = !canToggle;

    if (!canToggle) {
        toggleQuestionVisibilityBtnEl.dataset.viewMode = "all";
        toggleQuestionVisibilityBtnEl.title = "表示視点を切り替え";
        toggleQuestionVisibilityBtnEl.setAttribute("aria-label", "表示視点を切り替え");
        return;
    }

    const viewModeCycle = getQuestionViewModeCycleForCurrentUser();
    if (!viewModeCycle.includes(questionerViewMode)) {
        questionerViewMode = viewModeCycle[0];
    }

    const modeLabels = {
        all: "全開示",
        "team-left": "先攻視点",
        "team-right": "後攻視点",
    };

    const currentIndex = viewModeCycle.indexOf(questionerViewMode);
    const safeIndex = currentIndex >= 0 ? currentIndex : 0;
    const nextMode = viewModeCycle[(safeIndex + 1) % viewModeCycle.length];

    const currentModeLabel = modeLabels[questionerViewMode] || modeLabels.all;
    toggleQuestionVisibilityBtnEl.dataset.viewMode = questionerViewMode;
    toggleQuestionVisibilityBtnEl.title = `現在: ${currentModeLabel} / 次: ${modeLabels[nextMode]}`;
    toggleQuestionVisibilityBtnEl.setAttribute("aria-label", `表示視点: ${currentModeLabel}`);
}

function updateStartGameButtonVisibility(currentRoom) {
    if (!startGameBtnEl && !shuffleParticipantsBtnEl) return;

    const roomState = currentRoom?.game_state ?? currentRoomGameState ?? null;
    const canSee = isInGameArena() && userRole === "questioner" && roomState === "waiting";
    startGameBtnEl?.classList.toggle("hidden", !canSee);
    shuffleParticipantsBtnEl?.classList.toggle("hidden", !canSee);

    if (!canSee) {
        if (startGameBtnEl) startGameBtnEl.disabled = true;
        if (shuffleParticipantsBtnEl) shuffleParticipantsBtnEl.disabled = true;
        return;
    }

    const leftCount = Array.isArray(currentRoom?.left_participants) ? currentRoom.left_participants.length : 0;
    const rightCount = Array.isArray(currentRoom?.right_participants) ? currentRoom.right_participants.length : 0;
    const canStart = leftCount > 0 && rightCount > 0;
    if (startGameBtnEl) {
        startGameBtnEl.disabled = !canStart;
        startGameBtnEl.title = canStart ? "ゲームを開始" : "先攻と後攻に参加者が必要です";
    }

    const participantCount = leftCount + rightCount;
    const canShuffle = participantCount >= 2;
    if (shuffleParticipantsBtnEl) {
        shuffleParticipantsBtnEl.disabled = !canShuffle;
        shuffleParticipantsBtnEl.title = canShuffle ? "参加者をシャッフル" : "参加者が2人以上必要です";
    }
}

function closeAllModals() {
    setArenaCharClickGuard();
    alertModal.classList.add("hidden");
    confirmModal.classList.add("hidden");
    const judgementModal = document.getElementById("answer-judgement-modal");
    if (judgementModal) {
        judgementModal.classList.add("hidden");
    }
    updateArenaInteractionLock();
}

function showAlertModal(message) {
    return new Promise((resolve) => {
        alertMessageEl.textContent = message;
        alertModal.classList.remove("hidden");
        alertOkBtn.focus();
        setArenaCharClickGuard();
        updateArenaInteractionLock();

        const close = () => {
            setArenaCharClickGuard();
            alertModal.classList.add("hidden");
            alertOkBtn.removeEventListener("click", onOk);
            alertModal.removeEventListener("click", onBackdropClick);
            document.removeEventListener("keydown", onEscape);
            updateArenaInteractionLock();
            resolve();
        };

        const onOk = () => close();
        const onBackdropClick = (event) => {
            if (event.target === alertModal) {
                close();
            }
        };
        const onEscape = (event) => {
            if (event.key === "Escape") {
                close();
            }
        };

        alertOkBtn.addEventListener("click", onOk, { once: true });
        alertModal.addEventListener("click", onBackdropClick);
        document.addEventListener("keydown", onEscape);
    });
}

function showQuestionConfirmModal(questionText) {
    return new Promise((resolve) => {
        confirmMessageEl.textContent = `以下の問題文で出題しますか？\n\nQ. ${questionText}`;
        confirmModal.classList.remove("hidden");
        confirmOkBtn.focus();
        setArenaCharClickGuard();
        updateArenaInteractionLock();

        const close = (result) => {
            setArenaCharClickGuard();
            confirmModal.classList.add("hidden");
            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancel);
            confirmModal.removeEventListener("click", onBackdropClick);
            document.removeEventListener("keydown", onEscape);
            updateArenaInteractionLock();
            resolve(result);
        };

        const onOk = () => close(true);
        const onCancel = () => close(false);
        const onBackdropClick = (event) => {
            if (event.target === confirmModal) {
                close(false);
            }
        };
        const onEscape = (event) => {
            if (event.key === "Escape") {
                close(false);
            }
        };

        confirmOkBtn.addEventListener("click", onOk, { once: true });
        confirmCancelBtn.addEventListener("click", onCancel, { once: true });
        confirmModal.addEventListener("click", onBackdropClick);
        document.addEventListener("keydown", onEscape);
    });
}

function showConfirmModal(message, options = {}) {
    const { hideCancel = false, okLabel = "送信する", cancelLabel = "キャンセル" } = options;
    return new Promise((resolve) => {
        confirmMessageEl.textContent = message;
        confirmOkBtn.textContent = okLabel;
        confirmCancelBtn.textContent = cancelLabel;
        confirmCancelBtn.style.display = hideCancel ? "none" : "";
        confirmActionsEl.classList.toggle("single", hideCancel);
        confirmModal.classList.remove("hidden");
        confirmOkBtn.focus();
        setArenaCharClickGuard();
        updateArenaInteractionLock();

        const close = (result) => {
            setArenaCharClickGuard();
            confirmModal.classList.add("hidden");
            confirmCancelBtn.style.display = "";
            confirmActionsEl.classList.remove("single");
            confirmOkBtn.textContent = "送信する";
            confirmCancelBtn.textContent = "キャンセル";
            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancel);
            confirmModal.removeEventListener("click", onBackdropClick);
            document.removeEventListener("keydown", onEscape);
            updateArenaInteractionLock();
            resolve(result);
        };

        const onOk = () => close(true);
        const onCancel = () => close(false);
        const onBackdropClick = (event) => {
            if (event.target === confirmModal) {
                close(hideCancel ? true : false);
            }
        };
        const onEscape = (event) => {
            if (event.key === "Escape") {
                close(hideCancel ? true : false);
            }
        };

        confirmOkBtn.addEventListener("click", onOk, { once: true });
        confirmCancelBtn.addEventListener("click", onCancel, { once: true });
        confirmModal.addEventListener("click", onBackdropClick);
        document.addEventListener("keydown", onEscape);
    });
}

function renderParticipants(participants) {
    const listEl = document.getElementById("participants-list");
    listEl.innerHTML = "";

    if (!Array.isArray(participants) || participants.length === 0) {
        const emptyItem = document.createElement("li");
        emptyItem.textContent = "参加者はいません";
        listEl.appendChild(emptyItem);
        return;
    }

    participants.forEach((participant) => {
        const item = document.createElement("li");
        const nickname = participant.nickname || "ゲスト";
        const isMe = participant.client_id === myClientId;
        item.textContent = isMe ? `${nickname} (You)` : nickname;
        listEl.appendChild(item);
    });
}

function renderNameList(listEl, names) {
    listEl.innerHTML = "";
    if (!Array.isArray(names) || names.length === 0) {
        const emptyItem = document.createElement("li");
        emptyItem.textContent = "なし";
        listEl.appendChild(emptyItem);
        return;
    }

    names.forEach((entry) => {
        const item = document.createElement("li");
        if (typeof entry === "string") {
            item.textContent = entry;
            listEl.appendChild(item);
            return;
        }

        const nickname = entry?.nickname || "ゲスト";
        const isMe = entry?.client_id === myClientId;
        item.textContent = isMe ? `${nickname} (You)` : nickname;
        listEl.appendChild(item);
    });
}

function splitIntoGraphemes(text) {
    if (typeof text !== "string" || text.length === 0) return [];

    // サーバー側のインデックス計算と一致させるため、NFC正規化 + code point単位で分割する。
    const normalized = text.normalize("NFC");
    return Array.from(normalized);
}

function getNormalizedArenaQuestionChars() {
    const graphemes = splitIntoGraphemes(String(currentArenaQuestionRawText || ""));
    return graphemes.filter((ch) => ch !== "\n" && ch !== "\r");
}

function isDefaultPunctuationChar(ch) {
    if (typeof ch !== "string" || ch.length === 0) return false;
    if (ch === ARENA_MASK_CHAR) return false;

    // 句読点や一般的な記号をデフォルト選択対象にする。
    return /[\p{P}\p{S}]/u.test(ch);
}

function ensureDefaultPunctuationSelection() {
    if (!canSelectArenaQuestionChars()) {
        return;
    }

    const normalized = getNormalizedArenaQuestionChars();
    const questionKey = normalized.join("");
    if (questionKey === "") {
        selectedArenaQuestionCharIndexes.clear();
        lastAutoSelectedQuestionKey = null;
        return;
    }

    if (lastAutoSelectedQuestionKey === questionKey) {
        return;
    }

    selectedArenaQuestionCharIndexes.clear();
    normalized.forEach((ch, index) => {
        if (isDefaultPunctuationChar(ch)) {
            selectedArenaQuestionCharIndexes.add(index);
        }
    });

    lastAutoSelectedQuestionKey = questionKey;
}

function getArenaCharsPerLine() {
    const boardEl = document.getElementById("arena-question-board");
    const questionEl = document.getElementById("arena-question-text");
    if (!boardEl || !questionEl) {
        return 10;
    }

    const boardStyle = window.getComputedStyle(boardEl);
    const horizontalPadding = parseFloat(boardStyle.paddingLeft || "0") + parseFloat(boardStyle.paddingRight || "0");
    const availableWidth = Math.max(boardEl.clientWidth - horizontalPadding, 40);

    // 実際の描画スタイル（padding含む）で1文字幅を測る。
    const totalChars = Math.max(getNormalizedArenaQuestionChars().length, 1);
    const maxDigits = Math.max(String(totalChars).length, 1);
    const probeCharEl = document.createElement("span");
    probeCharEl.className = "arena-question-char is-mask-token";
    probeCharEl.dataset.tokenLabel = "8".repeat(maxDigits);
    probeCharEl.textContent = "";
    probeCharEl.style.visibility = "hidden";
    probeCharEl.style.position = "absolute";
    probeCharEl.style.left = "-9999px";
    probeCharEl.style.top = "-9999px";
    questionEl.appendChild(probeCharEl);

    const measuredCharWidth = Math.max(probeCharEl.getBoundingClientRect().width, 1);
    probeCharEl.remove();

    return Math.max(Math.floor(availableWidth / measuredCharWidth), ARENA_MIN_CHARS_PER_LINE);
}

function buildMaskedQuestionText(questionText, charsPerLine) {
    const graphemes = splitIntoGraphemes(String(questionText || ""));
    const normalized = graphemes.filter((ch) => ch !== "\n" && ch !== "\r");
    if (normalized.length === 0) {
        return "問題文を準備中...";
    }

    const lineLimit = Number.isFinite(charsPerLine) ? Math.max(Math.floor(charsPerLine), ARENA_MIN_CHARS_PER_LINE) : 10;

    let lineLength = 0;
    let output = "";

    normalized.forEach(() => {
        output += ARENA_MASK_CHAR;
        lineLength += 1;

        if (lineLength >= lineLimit) {
            output += "\n";
            lineLength = 0;
        }
    });

    return output.replace(/\n+$/g, "");
}

function buildPlainQuestionText(questionText, charsPerLine) {
    const graphemes = splitIntoGraphemes(String(questionText || ""));
    const normalized = graphemes.filter((ch) => ch !== "\n" && ch !== "\r");
    if (normalized.length === 0) {
        return "問題文を準備中...";
    }

    const lineLimit = Number.isFinite(charsPerLine) ? Math.max(Math.floor(charsPerLine), ARENA_MIN_CHARS_PER_LINE) : 10;

    let lineLength = 0;
    let output = "";

    normalized.forEach((ch) => {
        output += ch;
        lineLength += 1;

        if (lineLength >= lineLimit) {
            output += "\n";
            lineLength = 0;
        }
    });

    return output.replace(/\n+$/g, "");
}

function buildArenaQuestionRows(charsPerLine) {
    const normalized = getNormalizedArenaQuestionChars();
    if (normalized.length === 0) {
        return [];
    }

    const lineLimit = Number.isFinite(charsPerLine) ? Math.max(Math.floor(charsPerLine), ARENA_MIN_CHARS_PER_LINE) : 10;

    const rows = [];
    for (let i = 0; i < normalized.length; i += lineLimit) {
        rows.push(normalized.slice(i, i + lineLimit));
    }
    return rows;
}

function getEffectiveQuestionViewerRole() {
    if (questionerViewMode === "team-left") {
        return "team-left";
    }
    if (questionerViewMode === "team-right") {
        return "team-right";
    }

    // 全開示モードは出題者に加え、対戦終了後は全員が同じ表示を見られる。
    if (questionerViewMode === "all" && (userRole === "questioner" || isGameFinished())) {
        return "questioner";
    }

    return userRole;
}

function getOpenedByTeamMap() {
    const source = currentGameState?.opened_by_team;
    if (!source || typeof source !== "object") {
        return {};
    }
    return source;
}

function getDisplayCharForIndex(originalChar, index) {
    const openedByTeam = getOpenedByTeamMap();
    const owner = openedByTeam[String(index)];
    const tokenNumberText = String(index + 1);
    const viewerRole = getEffectiveQuestionViewerRole();

    if (viewerRole === "questioner") {
        return {
            text: originalChar,
            tokenVariant: null,
        };
    }

    if (!owner) {
        return {
            text: tokenNumberText,
            tokenVariant: "neutral",
        };
    }

    if (owner === "yakumono") {
        return {
            text: originalChar,
            tokenVariant: null,
        };
    }

    const canSeeOriginal = owner === viewerRole;
    if (canSeeOriginal) {
        return {
            text: originalChar,
            tokenVariant: null,
        };
    }

    // 相手陣営が取得した文字は色付き番号タイルで表示する
    if (owner === "team-left") {
        return {
            text: tokenNumberText,
            tokenVariant: "left",
        };
    }
    if (owner === "team-right") {
        return {
            text: tokenNumberText,
            tokenVariant: "right",
        };
    }

    return {
        text: tokenNumberText,
        tokenVariant: "neutral",
    };
}

function renderArenaQuestionCharGrid(questionEl, charsPerLine) {
    const rows = buildArenaQuestionRows(charsPerLine);
    if (rows.length === 0) {
        questionEl.textContent = "問題文を準備中...";
        selectedArenaQuestionCharIndexes.clear();
        return;
    }

    const selectableForSetup = canSelectArenaQuestionChars();
    const selectableForOpen = canRequestOpenCharacter();
    const selectable = selectableForSetup || selectableForOpen;
    const openedByTeam = getOpenedByTeamMap();
    const viewerRole = getEffectiveQuestionViewerRole();

    let totalChars = 0;
    rows.forEach((row) => {
        totalChars += row.length;
    });

    if (!selectableForSetup) {
        selectedArenaQuestionCharIndexes.clear();
        lastAutoSelectedQuestionKey = null;
    } else {
        for (const index of Array.from(selectedArenaQuestionCharIndexes)) {
            if (index < 0 || index >= totalChars) {
                selectedArenaQuestionCharIndexes.delete(index);
            }
        }
    }

    questionEl.textContent = "";
    const fragment = document.createDocumentFragment();
    let globalIndex = 0;

    rows.forEach((rowChars) => {
        const lineEl = document.createElement("span");
        lineEl.className = "arena-question-line";

        rowChars.forEach((char) => {
            const openedOwner = openedByTeam[String(globalIndex)];
            const isOpened = Boolean(openedOwner);
            const displayInfo = getDisplayCharForIndex(char, globalIndex);
            const charEl = document.createElement("span");
            charEl.className = "arena-question-char";
            charEl.setAttribute("aria-label", `文字 ${globalIndex + 1}`);
            charEl.dataset.charIndex = String(globalIndex);
            charEl.textContent = displayInfo.text;

            // どの経路でも空表示を避ける（白い穴に見える状態を防ぐ）
            if (charEl.textContent === "") {
                charEl.textContent = "□";
            }

            if (displayInfo.tokenVariant) {
                charEl.classList.add("is-mask-token");
                charEl.dataset.tokenLabel = displayInfo.text || String(globalIndex + 1);
                charEl.textContent = "";
                if (displayInfo.tokenVariant === "left") {
                    charEl.classList.add("is-owned-left");
                } else if (displayInfo.tokenVariant === "right") {
                    charEl.classList.add("is-owned-right");
                }
            }

            const isAllOpenMode = questionerViewMode === "all";
            const shouldHighlightOpenedInAllMode = (
                isAllOpenMode
                && viewerRole === "questioner"
                && displayInfo.tokenVariant == null
                && typeof openedOwner === "string"
            );
            if (shouldHighlightOpenedInAllMode) {
                if (openedOwner === "team-left") {
                    charEl.classList.add("is-revealed-left");
                } else if (openedOwner === "team-right") {
                    charEl.classList.add("is-revealed-right");
                } else if (openedOwner === "yakumono") {
                    // 約物は既存の選択色（黄色）を使って明示する。
                    charEl.classList.add("is-selected");
                }
            }

            // 参加者/観戦者視点で空白文字が開いた場合、白い穴に見えないように可視記号で描く。
            if (
                displayInfo.tokenVariant == null
                && viewerRole !== "questioner"
                && typeof displayInfo.text === "string"
                && displayInfo.text.trim() === ""
            ) {
                charEl.classList.add("is-whitespace-visible");
                charEl.textContent = "□";
                charEl.setAttribute("aria-label", `空白 文字 ${globalIndex + 1}`);
            }

            const canClickInSetup = selectableForSetup;
            const canClickInOpen = selectableForOpen && !isOpened;
            if (canClickInSetup || canClickInOpen) {
                charEl.classList.add("is-selectable");
                charEl.setAttribute("role", "button");
                // 参加者の文字オープン操作はタップ主体なので、フォーカス残留を避ける。
                charEl.setAttribute("tabindex", canClickInSetup ? "0" : "-1");
            } else {
                charEl.setAttribute("aria-disabled", "true");
            }

            if (selectableForSetup && selectedArenaQuestionCharIndexes.has(globalIndex)) {
                charEl.classList.add("is-selected");
            }

            lineEl.appendChild(charEl);
            globalIndex += 1;
        });

        fragment.appendChild(lineEl);
    });

    questionEl.appendChild(fragment);
}

function renderMaskedArenaQuestionText() {
    const questionEl = document.getElementById("arena-question-text");
    if (!questionEl) return;

    const charsPerLine = getArenaCharsPerLine();
    questionEl.textContent = buildMaskedQuestionText(currentArenaQuestionRawText, charsPerLine);
}

function renderArenaQuestionText() {
    const questionEl = document.getElementById("arena-question-text");
    if (!questionEl) return;

    const charsPerLine = getArenaCharsPerLine();
    renderArenaQuestionCharGrid(questionEl, charsPerLine);
}

function renderArena(currentRoom) {
    const titleEl = document.getElementById("arena-room-title");
    const questionEl = document.getElementById("arena-question-text");
    const leftListEl = document.getElementById("arena-player-left-list");
    const rightListEl = document.getElementById("arena-player-right-list");
    const spectatorListEl = document.getElementById("arena-spectator-list");

    if (!currentRoom) {
        titleEl.textContent = "出題者: -";
        currentArenaQuestionRawText = "";
        questionerViewMode = "all";
        selectedArenaQuestionCharIndexes.clear();
        lastAutoSelectedQuestionKey = null;
        questionEl.textContent = "問題文を準備中...";
        updateQuestionVisibilityButton();
        renderNameList(leftListEl, []);
        renderNameList(rightListEl, []);
        renderNameList(spectatorListEl, []);
        return;
    }

    const isMeQuestioner = currentRoom.questioner_id === myClientId;
    const questionerLabel = isMeQuestioner
        ? `${currentRoom.questioner_name} (You)`
        : currentRoom.questioner_name;
    titleEl.textContent = `出題者: ${questionerLabel}`;

    const serverQuestionText = String(currentRoom.question_text || "");
    const serverQuestionVisibleText = String(currentRoom.question_visible_text || "");
    const serverQuestionLength = Number(currentRoom.question_length || 0);

    if (userRole === "questioner" && serverQuestionText) {
        currentArenaQuestionRawText = serverQuestionText;
    } else if (serverQuestionVisibleText) {
        currentArenaQuestionRawText = serverQuestionVisibleText;
    } else if (Number.isFinite(serverQuestionLength) && serverQuestionLength > 0) {
        // サーバーが可視化文字列を返せないケースでは長さ情報だけで伏せ字表示を作る。
        currentArenaQuestionRawText = ARENA_MASK_CHAR.repeat(Math.floor(serverQuestionLength));
    } else {
        currentArenaQuestionRawText = "";
    }

    ensureDefaultPunctuationSelection();
    renderArenaQuestionText();
    updateQuestionVisibilityButton();

    const leftPlayers = Array.isArray(currentRoom.left_participants) ? currentRoom.left_participants : [];
    const rightPlayers = Array.isArray(currentRoom.right_participants) ? currentRoom.right_participants : [];

    renderNameList(leftListEl, leftPlayers);
    renderNameList(rightListEl, rightPlayers);
    renderNameList(spectatorListEl, currentRoom.spectators || []);
}

function requestRoomEntry(roomOwnerId, role) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    pendingArenaMode = "guest";

    const payload = {
        type: "room_entry",
        room_owner_id: roomOwnerId,
        role,
        timestamp: Date.now()
    };
    ws.send(JSON.stringify(payload));
}

function renderRooms(rooms) {
    const roomListEl = document.getElementById("room-list");
    roomListEl.innerHTML = "";

    if (!Array.isArray(rooms) || rooms.length === 0) {
        const emptyEl = document.createElement("div");
        emptyEl.className = "room-card-empty";
        emptyEl.textContent = "現在、出題中の部屋はありません";
        roomListEl.appendChild(emptyEl);
        return;
    }

    rooms.forEach((room) => {
        const card = document.createElement("div");
        card.className = "room-card";

        const questionerEl = document.createElement("div");
        questionerEl.className = "room-card-questioner";
        questionerEl.textContent = `${room.questioner_name} の出題部屋`;

        const metaEl = document.createElement("div");
        metaEl.className = "room-card-meta";
        const roomState = String(room.game_state || "waiting");
        const gameStateLabelByState = {
            waiting: "準備中",
            playing: "対戦中",
            finished: "対戦終了",
        };
        const gameStateLabel = gameStateLabelByState[roomState] || "準備中";
        metaEl.textContent = `状態 ${gameStateLabel} / 参加 ${room.participant_count}人 / 観戦 ${room.spectator_count}人`;

        if (!room.is_owner) {
            const actionsEl = document.createElement("div");
            actionsEl.className = "room-card-actions";

            const watchBtn = document.createElement("button");
            watchBtn.type = "button";
            watchBtn.className = "room-card-btn secondary";
            watchBtn.textContent = "観戦";

            watchBtn.addEventListener("click", () => requestRoomEntry(room.room_owner_id, "spectator"));

            if (room.can_join_as_participant !== false) {
                const joinBtn = document.createElement("button");
                joinBtn.type = "button";
                joinBtn.className = "room-card-btn";
                joinBtn.textContent = "参加";
                joinBtn.addEventListener("click", () => requestRoomEntry(room.room_owner_id, "participant"));
                actionsEl.appendChild(joinBtn);
            }
            actionsEl.appendChild(watchBtn);
            card.appendChild(actionsEl);
        }

        card.appendChild(questionerEl);
        card.appendChild(metaEl);
        roomListEl.appendChild(card);
    });
}

function createEventLogItem(eventType, eventMessage) {
    if (!eventMessage) {
        return null;
    }

    const item = document.createElement("div");
    item.className = "event-log-item";

    const messageEl = document.createElement("span");
    messageEl.className = "event-log-message";

    const buildSplitMessage = (nameClass, bodyClass, matchResult) => {
        const nameEl = document.createElement("span");
        nameEl.className = nameClass;
        nameEl.textContent = matchResult[1];

        const bodyEl = document.createElement("span");
        bodyEl.className = bodyClass;
        bodyEl.textContent = matchResult[2];

        messageEl.appendChild(nameEl);
        messageEl.appendChild(bodyEl);
    };

    if (eventType === "chat") {
        const separatorMatch = eventMessage.match(/^([^:：]+[:：]\s*)([\s\S]*)$/);
        if (separatorMatch) {
            messageEl.classList.add("chat");
            buildSplitMessage("event-log-chat-name", "event-log-chat-body", separatorMatch);
        } else {
            messageEl.textContent = eventMessage;
        }
    } else if (eventType === "join" || eventType === "leave" || eventType === "question") {
        const systemMatch = eventMessage.match(/^(.+?)(\s*が[\s\S]*)$/);
        if (systemMatch) {
            messageEl.classList.add("system");
            buildSplitMessage("event-log-system-name", "event-log-system-body", systemMatch);
        } else {
            messageEl.textContent = eventMessage;
        }
    } else {
        messageEl.textContent = eventMessage;
    }

    const timestampEl = document.createElement("span");
    timestampEl.className = "event-log-time";
    timestampEl.textContent = new Date().toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });

    item.appendChild(messageEl);
    item.appendChild(timestampEl);
    return item;
}

function appendLogToContainer(logEl, eventType, eventMessage) {
    if (!logEl) {
        return;
    }

    const item = createEventLogItem(eventType, eventMessage);
    if (!item) {
        return;
    }

    logEl.appendChild(item);
    while (logEl.children.length > 50) {
        logEl.removeChild(logEl.firstChild);
    }

    logEl.scrollTop = logEl.scrollHeight;
}

function appendEventLog(eventType, eventMessage, eventChatType = null) {
    const allowedTypes = new Set([
        "join",
        "leave",
        "question",
        "chat",
        "room_shuffle",
        "open_vote_request",
        "open_vote_resolved",
        "answer_vote_request",
        "answer_vote_resolved",
        "turn_end_vote_request",
        "turn_end_vote_resolved",
    ]);
    if (!allowedTypes.has(eventType) || !eventMessage) {
        return;
    }

    // チャット種別が指定されているイベントは、対応するゲーム内ログに流す。
    if (eventChatType && eventChatType !== "lobby") {
        const roomLogEl = document.getElementById(`game-chat-log-${eventChatType}`);
        appendLogToContainer(roomLogEl, eventType, eventMessage);
        return;
    }

    // アリーナ内で発生するゲーム進行ログは待機所ログへは送らない。
    const arenaOnlyTypes = new Set([
        "room_shuffle",
        "open_vote_request",
        "open_vote_resolved",
        "answer_vote_request",
        "answer_vote_resolved",
        "turn_end_vote_request",
        "turn_end_vote_resolved",
    ]);
    if (arenaOnlyTypes.has(eventType)) {
        return;
    }

    const waitingLogEl = document.getElementById("event-log");
    appendLogToContainer(waitingLogEl, eventType, eventMessage);
}

function buildWebSocketUrl(clientId, nickname) {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = new URL(window.location.origin);
    wsUrl.protocol = wsProtocol;
    wsUrl.pathname = `/ws/${encodeURIComponent(clientId)}`;
    wsUrl.searchParams.set("nickname", nickname);
    return wsUrl.toString();
}

window.onload = () => {
    const savedNickname = localStorage.getItem("quiz_nickname");

    if (savedNickname) {
        document.getElementById("nickname").value = savedNickname;
    }
};

// 「ゲームに参加」ボタンを押したときの処理
document.getElementById("join-btn").addEventListener("click", async () => {
    const nicknameInput = document.getElementById("nickname").value.trim();
    if (nicknameInput === "") {
        await showAlertModal("ニックネームを入力してください");
        return;
    }
    localStorage.setItem("quiz_nickname", nicknameInput);

    const clientId = crypto.randomUUID();
    myClientId = clientId;

    const wsUrl = buildWebSocketUrl(clientId, nicknameInput);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log("サーバーに接続しました");
        document.getElementById("login-screen").style.display = "none";
        showWaitingRoomScreen();
        document.getElementById("my-name").textContent = nicknameInput;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        currentRoomSnapshot = data.current_room ?? null;
        userRole = data.current_room?.chat_role ?? null;
        currentRoomGameState = data.current_room?.game_state ?? null;
        currentGameState = data.current_room?.game ?? null;
        if (data.target_screen === "game_arena") {
            updateArenaLeaveLabel(pendingArenaMode === "owner" ? "owner" : "guest");
            showGameArenaScreen();
        } else if (data.target_screen === "waiting_room") {
            pendingArenaMode = null;
            updateArenaLeaveLabel("guest");
            showWaitingRoomScreen();
        }

        if (data.event_type === "forced_exit_notice" && data.private_info) {
            closeAllModals();
            void showConfirmModal(data.private_info, { hideCancel: true, okLabel: "OK" });
        } else if (data.event_type === "private_notice" && data.private_info) {
            closeAllModals();
            void showAlertModal(data.private_info);
        }

        if (data.event_type === "open_vote_request" && data.event_payload) {
            void handleOpenVoteRequest(data.event_payload);
        }
        if (data.event_type === "answer_vote_request" && data.event_payload) {
            void handleAnswerVoteRequest(data.event_payload);
        }
        if (data.event_type === "turn_end_vote_request" && data.event_payload) {
            void handleTurnEndVoteRequest(data.event_payload);
        }
        if (data.event_type === "answer_judgement_request" && data.event_payload) {
            void handleAnswerJudgementRequest(data.event_payload);
        }

        appendEventLog(data.event_type, data.event_message, data.event_chat_type);
        renderRooms(data.rooms);
        renderParticipants(data.participants);
        renderArena(data.current_room);
        updateGameStateUI();
        updateStartGameButtonVisibility(data.current_room);
        updateArenaAnswerFormVisibility();
        updateChatBoxVisibility();
    };
});

document.getElementById("nickname").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    document.getElementById("join-btn").click();
});

async function submitQuestion() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    const questionInput = document.getElementById("question-box");
    const questionText = questionInput.value.trim();
    if (questionText === "") {
        await showAlertModal("問題を入力してください");
        return;
    }

    const confirmed = await showQuestionConfirmModal(questionText);
    if (!confirmed) {
        return;
    }

    const questionPayload = {
        type: "question_submission",
        question_text: questionText,
        timestamp: Date.now()
    };

    pendingArenaMode = "owner";
    ws.send(JSON.stringify(questionPayload));
    questionInput.value = "";
}

document.getElementById("submit-question-btn").addEventListener("click", () => {
    submitQuestion();
});

document.getElementById("question-box").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    submitQuestion();
});

async function requestRoomExit() {
    const isQuestioner = userRole === "questioner";
    const confirmMessage = isQuestioner
        ? "部屋を閉じると参加者と観戦者は全員退室になります。\n\n本当に部屋を閉じますか？"
        : "本当に退室しますか？";
    const okLabel = isQuestioner ? "部屋を閉じる" : "退室する";

    const confirmed = await showConfirmModal(confirmMessage, {
        okLabel,
        cancelLabel: "キャンセル"
    });
    if (!confirmed) {
        return;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "room_exit" }));
    }
    pendingArenaMode = null;
    updateArenaLeaveLabel("guest");
    showWaitingRoomScreen();
}

function sendChatMessage(chatBoxEl) {
    if (!chatBoxEl) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        void showAlertModal("サーバー接続後にチャットを送信できます");
        return;
    }

    const inputEl = chatBoxEl.querySelector(".chat-input");
    if (!inputEl) return;

    const message = inputEl.value.trim();
    if (message === "") return;

    if (message.length > CHAT_MAX_LENGTH) {
        void showAlertModal(`チャットは${CHAT_MAX_LENGTH}文字以内で送信してください`);
        return;
    }

    const chatType = chatBoxEl.getAttribute("data-chat-type") || "lobby";
    if (!canSendChatType(chatType)) {
        void showAlertModal("このチャット欄では発言できません。");
        return;
    }

    const now = Date.now();
    const lastSent = lastChatSentAt[chatType] || 0;

    if (now - lastSent < CHAT_MIN_INTERVAL_MS) {
        const waitMs = CHAT_MIN_INTERVAL_MS - (now - lastSent);
        void showAlertModal(`連続投稿が早すぎます。${(waitMs / 1000).toFixed(1)}秒待ってください`);
        return;
    }

    ws.send(
        JSON.stringify({
            type: "chat_message",
            message,
            chat_type: chatType,
            timestamp: Date.now()
        })
    );
    lastChatSentAt[chatType] = now;
    inputEl.value = "";
    updateChatLengthWarning(inputEl);
}

function bindChatHandlers() {
    // イベント委譲：全チャットボックスの送信ボタン
    document.addEventListener("click", (event) => {
        if (event.target.classList.contains("chat-send-btn")) {
            const chatBox = event.target.closest(".chat-box");
            if (chatBox) {
                sendChatMessage(chatBox);
            }
        }
    });

    // イベント委譲：全チャットボックスの入力欄
    document.addEventListener("input", (event) => {
        if (event.target.classList.contains("chat-input")) {
            updateChatLengthWarning(event.target);
        }
    });

    // イベント委譲：Enterキーで送信
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;

        if (event.target.classList.contains("chat-input")) {
            event.preventDefault();
            const chatBox = event.target.closest(".chat-box");
            if (chatBox) {
                sendChatMessage(chatBox);
            }
        }
    });
}

bindChatHandlers();

function toggleArenaQuestionCharSelectionFromTarget(targetEl) {
    const charEl = targetEl?.closest?.(".arena-question-char");
    if (!charEl) return;

    const index = Number(charEl.dataset.charIndex);
    if (!Number.isFinite(index)) return;
    const isOpened = Boolean(getOpenedByTeamMap()[String(index)]);

    if (canSelectArenaQuestionChars()) {
        if (selectedArenaQuestionCharIndexes.has(index)) {
            selectedArenaQuestionCharIndexes.delete(index);
        } else {
            selectedArenaQuestionCharIndexes.add(index);
        }

        renderArenaQuestionText();
        return;
    }

    if (canRequestOpenCharacter()) {
        if (isOpened) {
            return;
        }
        void requestOpenVote(index);
    }
}

async function requestOpenVote(charIndex) {
    if (openVoteRequestPending) {
        await showAlertModal("投票開始処理中です。少し待ってください。");
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const teamParticipantCount = getCurrentTeamParticipantCount();
    const isProposalMode = teamParticipantCount > 1;
    if (isProposalMode) {
        const confirmed = await showConfirmModal(
            `${charIndex + 1}文字目オープンを提案しますか？`,
            {
                okLabel: "提案する",
                cancelLabel: "キャンセル",
            }
        );
        if (!confirmed) {
            return;
        }
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    openVoteRequestPending = true;
    ws.send(
        JSON.stringify({
            type: "open_vote_request",
            char_index: charIndex,
            timestamp: Date.now()
        })
    );

    window.setTimeout(() => {
        openVoteRequestPending = false;
    }, 800);
}

async function handleOpenVoteRequest(payload) {
    const voteId = String(payload?.vote_id || "");
    const charIndex = Number(payload?.char_index);
    const totalVoters = Number(payload?.total_voters || 0);
    if (!voteId || !Number.isFinite(charIndex)) return;
    if (handledOpenVoteIds.has(voteId)) return;

    handledOpenVoteIds.add(voteId);

    const majorityNote = totalVoters > 1
        ? "\n（陣営の過半数OKで実行されます）"
        : "";

    const confirmed = await showConfirmModal(
        `${charIndex + 1}文字目をオープンしますか？${majorityNote}`,
        {
            okLabel: "OK",
            cancelLabel: "キャンセル"
        }
    );

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "open_vote_response",
            vote_id: voteId,
            approve: Boolean(confirmed),
            timestamp: Date.now()
        })
    );
}

async function handleAnswerVoteRequest(payload) {
    const voteId = String(payload?.vote_id || "");
    const teamLabel = String(payload?.team_label || "");
    const answererName = String(payload?.answerer_name || "参加者");
    const answerText = String(payload?.answer_text || "");
    const totalVoters = Number(payload?.total_voters || 0);

    if (!voteId) return;
    if (handledAnswerVoteIds.has(voteId)) return;
    handledAnswerVoteIds.add(voteId);

    const unanimityNote = totalVoters > 1
        ? "\n（陣営全員のOKで送信されます）"
        : "";

    const confirmed = await showConfirmModal(
        `${teamLabel} ${answererName} の解答案:\n${answerText}\n\nこの内容で解答を送信しますか？${unanimityNote}`,
        {
            okLabel: "OK",
            cancelLabel: "キャンセル",
        }
    );

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "answer_vote_response",
            vote_id: voteId,
            approve: Boolean(confirmed),
            timestamp: Date.now(),
        })
    );
}

async function handleTurnEndVoteRequest(payload) {
    const voteId = String(payload?.vote_id || "");
    const teamLabel = String(payload?.team_label || "");
    const totalVoters = Number(payload?.total_voters || 0);
    if (!voteId) return;
    if (handledTurnEndVoteIds.has(voteId)) return;

    handledTurnEndVoteIds.add(voteId);

    const majorityNote = totalVoters > 1
        ? "\n（陣営の過半数OKで実行されます）"
        : "";
    const confirmed = await showConfirmModal(
        `${teamLabel}陣営でターンエンドしますか？${majorityNote}`,
        {
            okLabel: "OK",
            cancelLabel: "キャンセル",
        }
    );

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "turn_end_vote_response",
            vote_id: voteId,
            approve: Boolean(confirmed),
            timestamp: Date.now(),
        })
    );
}

async function handleAnswerJudgementRequest(payload) {
    if (userRole !== "questioner") {
        return;
    }

    const team = String(payload?.team || "");
    const teamLabel = team === "team-left" ? "先攻" : "後攻";
    const answererName = String(payload?.answerer_name || "参加者");
    const answerText = String(payload?.answer_text || "");

    const confirmed = await showConfirmModal(
        `${teamLabel} ${answererName} の解答:\n${answerText}\n\n正誤を判定してください。`,
        {
            okLabel: "正解",
            cancelLabel: "誤答",
        }
    );

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "judge_answer",
            is_correct: Boolean(confirmed),
            timestamp: Date.now(),
        })
    );
}

document.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.closest(".modal")) {
        return;
    }
    if (shouldSuppressArenaCharClick()) {
        return;
    }
    toggleArenaQuestionCharSelectionFromTarget(event.target);
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
        return;
    }

    const targetEl = event.target;
    if (!(targetEl instanceof HTMLElement) || !targetEl.classList.contains("arena-question-char")) {
        return;
    }

    event.preventDefault();
    toggleArenaQuestionCharSelectionFromTarget(targetEl);
});

startGameBtnEl?.addEventListener("click", async () => {
    const confirmed = await showConfirmModal("ゲームを開始しますか？", {
        okLabel: "開始する",
        cancelLabel: "キャンセル"
    });
    if (!confirmed) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        void showAlertModal("サーバー接続後に操作できます");
        return;
    }

    ws.send(
        JSON.stringify({
            type: "start_game",
            selected_char_indexes: Array.from(selectedArenaQuestionCharIndexes).sort((a, b) => a - b),
            timestamp: Date.now()
        })
    );
});

shuffleParticipantsBtnEl?.addEventListener("click", async () => {
    const confirmed = await showConfirmModal(
        "参加者をシャッフルして先攻・後攻を再割り当てします。\n実行しますか？",
        {
            okLabel: "シャッフル",
            cancelLabel: "キャンセル"
        }
    );
    if (!confirmed) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        void showAlertModal("サーバー接続後に操作できます");
        return;
    }

    ws.send(
        JSON.stringify({
            type: "shuffle_participants",
            timestamp: Date.now()
        })
    );
});

toggleQuestionVisibilityBtnEl?.addEventListener("click", () => {
    if (!canToggleQuestionViewMode()) {
        return;
    }

    const viewModeCycle = getQuestionViewModeCycleForCurrentUser();
    if (!viewModeCycle.includes(questionerViewMode)) {
        questionerViewMode = viewModeCycle[0];
    }

    const currentIndex = viewModeCycle.indexOf(questionerViewMode);
    const safeIndex = currentIndex >= 0 ? currentIndex : 0;
    questionerViewMode = viewModeCycle[(safeIndex + 1) % viewModeCycle.length];
    updateQuestionVisibilityButton();
    renderArenaQuestionText();
});

arenaAnswerSubmitBtnEl?.addEventListener("click", () => {
    void submitArenaAnswer();
});

arenaTurnEndBtnEl?.addEventListener("click", () => {
    void submitTurnEndAttempt();
});

arenaAnswerInputEl?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) {
        return;
    }

    event.preventDefault();
    void submitArenaAnswer();
});

window.addEventListener("resize", () => {
    syncArenaPlayerBoxHeights();
    if (isInGameArena()) {
        renderArenaQuestionText();
    }
    updateViewportDebugOverlay();
});

leaveGameArenaEl?.addEventListener("click", requestRoomExit);
leaveGameArenaEl?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        requestRoomExit();
    }
});

function showRulebookModal(triggerEl = null) {
    if (!rulebookModalEl) return;
    if (triggerEl instanceof HTMLElement) {
        lastRulebookTriggerEl = triggerEl;
    }
    rulebookModalEl.classList.remove("hidden");
    updateArenaInteractionLock();
    rulebookCloseBtnEl?.focus();
}

function closeRulebookModal() {
    if (!rulebookModalEl) return;
    setArenaCharClickGuard();
    rulebookModalEl.classList.add("hidden");
    updateArenaInteractionLock();
    lastRulebookTriggerEl?.focus();
}

function bindRulebookHandlers() {
    removeWhitespaceTextNodes(rulebookContentEl);

    rulebookTriggerEls.forEach((buttonEl) => {
        buttonEl.addEventListener("click", () => {
            showRulebookModal(buttonEl);
        });
    });

    if (rulebookCloseBtnEl) {
        rulebookCloseBtnEl.addEventListener("click", closeRulebookModal);
    }

    if (rulebookModalEl) {
        rulebookModalEl.addEventListener("click", (event) => {
            if (event.target === rulebookModalEl) {
                closeRulebookModal();
            }
        });
    }

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !rulebookModalEl.classList.contains("hidden")) {
            closeRulebookModal();
        }
    });
}

bindRulebookHandlers();
updateViewportDebugOverlay();

