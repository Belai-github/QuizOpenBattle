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
const questionInputEl = document.getElementById("question-box");
const questionLengthWarningEl = document.getElementById("question-length-warning");
const questionLengthCounterEl = document.getElementById("question-length-counter");
const leaveGameArenaEl = document.getElementById("leave-game-arena");
const closeRoomBtnEl = document.getElementById("close-room-btn");
const startGameBtnEl = document.getElementById("start-game-btn");
const shuffleParticipantsBtnEl = document.getElementById("shuffle-participants-btn");
const toggleQuestionVisibilityBtnEl = document.getElementById("toggle-question-visibility-btn");
const arenaGlobalChatBoxEl = document.getElementById("arena-global-chat-box");
const arenaLogsModalEl = document.getElementById("arena-logs-modal");
const arenaLogsModalSlotEl = document.getElementById("arena-logs-modal-slot");
const arenaAnswerBoxEl = document.getElementById("arena-answer-box");
const arenaAnswerInputEl = document.getElementById("arena-answer-input");
const arenaAnswerLengthWarningEl = document.getElementById("arena-answer-length-warning");
const arenaAnswerSubmitBtnEl = document.getElementById("arena-answer-submit-btn");
const arenaIntentionalDrawBtnEl = document.getElementById("arena-intentional-draw-btn");
const arenaTurnEndBtnEl = document.getElementById("arena-turn-end-btn");
const openKifuListBtnEl = document.getElementById("open-kifu-list-btn");
const aiQuestionBtnEl = document.getElementById("ai-question-btn");
const aiQuestionSpinnerEl = document.getElementById("ai-question-spinner");
const aiQuestionModalEl = document.getElementById("ai-question-modal");
const aiGenreInputEl = document.getElementById("ai-genre-input");
const aiModelSelectEl = document.getElementById("ai-model-select");
const aiAccuracyRateRangeEl = document.getElementById("ai-accuracy-rate-range");
const aiAccuracyRateValueEl = document.getElementById("ai-accuracy-rate-value");
const aiQuestionModalCancelBtnEl = document.getElementById("ai-question-cancel-btn");
const aiQuestionModalSubmitBtnEl = document.getElementById("ai-question-submit-btn");
const kifuListScreenEl = document.getElementById("kifu-list-screen");
const kifuListEl = document.getElementById("kifu-list");
const kifuListBackLinkEl = document.getElementById("kifu-list-back-link");
const kifuReplayControlsEl = document.getElementById("kifu-replay-controls");
const kifuStepFirstBtnEl = document.getElementById("kifu-step-first-btn");
const kifuStepPrevBtnEl = document.getElementById("kifu-step-prev-btn");
const kifuStepNextBtnEl = document.getElementById("kifu-step-next-btn");
const kifuStepLastBtnEl = document.getElementById("kifu-step-last-btn");
const kifuStepLabelEl = document.getElementById("kifu-step-label");
const rulebookTriggerEls = document.querySelectorAll(".rulebook-trigger");
const rulebookModalEl = document.getElementById("rulebook-modal");
const rulebookContentEl = document.getElementById("rulebook-content");
const rulebookCloseBtnEl = document.getElementById("rulebook-close-btn");

let pendingArenaMode = null;
let userRole = null; // "questioner", "team-left", "team-right", "spectator", null
let currentRoomGameState = null; // "waiting" | "playing" | "finished" | null
let currentGameState = null; // game中の詳細状態: {current_turn_team, team_left: {...}, team_right: {...}, ...}
let currentRoomSnapshot = null;
let currentRoomsSnapshot = [];
let currentKifuList = [];
let currentKifuDetail = null;
let currentKifuSteps = [];
let currentKifuStepIndex = 0;
let isKifuMode = false;
let isArenaReplayMode = false;
let currentArenaReplayRoomId = null;
let arenaReplayLoadToken = 0;
let arenaReplayPendingRequestKey = "";
const handledOpenVoteIds = new Set();
const handledAnswerVoteIds = new Set();
const handledTurnEndVoteIds = new Set();
const handledIntentionalDrawVoteIds = new Set();
let openVoteRequestPending = false;
let turnEndRequestPending = false;
let intentionalDrawVoteRequestPending = false;
const QUESTION_MAX_LENGTH = 100;
const ANSWER_MAX_LENGTH = 100;
const CHAT_MAX_LENGTH = 200;
const CHAT_MIN_INTERVAL_MS = 800;
let aiModelOptions = [];
let aiModelOptionsById = new Map();
let defaultAiModelId = "";
let aiModelsLoaded = false;
const DEFAULT_AI_ACCURACY_RATE = 70;
const MIN_AI_ACCURACY_RATE = 10;
const ARENA_MASK_CHAR = "■";
const ARENA_MIN_CHARS_PER_LINE = 4;
const QUESTIONER_VIEW_MODE_CYCLE = ["all", "team-left", "team-right"];
const SPECTATOR_VIEW_MODE_CYCLE = ["team-left", "team-right"];
const DEBUG_VIEWPORT_OVERLAY_ENABLED = false;
let currentArenaQuestionRawText = "";
let questionerViewMode = "all";
const selectedArenaQuestionCharIndexes = new Set();
let lastAutoSelectedQuestionKey = null;
const lastChatSentAt = {}; // key: "lobby" or "game-all", "team-left", "team-right", "questioner"
let lastRulebookTriggerEl = null;
let viewportDebugEl = null;
let previousRoomGameState = null;
let connectionTimeoutModalShown = false;
let isConnecting = false;
let aiQuestionRequestPending = false;
let aiQuestionGenerationActive = false;
let aiQuestionGenerationOwnerId = null;
const LOG_AUTO_SCROLL_THRESHOLD_PX = 16;
const logNewIndicatorMap = new WeakMap();
const logScrollListenerBound = new WeakSet();
const chatLogFilterStateById = new Map();
const chatLogFilterControlById = new Map();
const ARENA_CHAT_TYPES = ["team-left", "team-right", "game-global"];
const REPLAY_PROGRESS_EVENT_TYPES = new Set(["character_opened", "answer_attempt", "answer_result", "turn_changed", "intentional_draw"]);
const ARENA_VOTE_EVENT_TYPES = new Set([
    "open_vote_request",
    "open_vote_resolved",
    "answer_vote_request",
    "answer_vote_resolved",
    "turn_end_vote_request",
    "turn_end_vote_resolved",
    "intentional_draw_vote_request",
    "intentional_draw_vote_resolved",
]);
const HIDDEN_ARENA_EVENT_TYPES = new Set([
    "open_vote_request",
    "open_vote_resolved",
    "answer_vote_request",
    "answer_vote_resolved",
    "turn_end_vote_request",
    "turn_end_vote_resolved",
    "intentional_draw_vote_request",
    "intentional_draw_vote_resolved",
]);
const ARENA_ALLOWED_EVENT_TYPES = new Set([
    "join",
    "leave",
    "room_entry",
    "room_exit",
    "room_reconnected",
    "game_start",
    "game_finished",
    "question",
    "chat",
    "room_shuffle",
    "character_opened",
    "answer_submitted",
    "open_vote_request",
    "open_vote_resolved",
    "answer_attempt",
    "answer_result",
    "answer_vote_request",
    "answer_vote_resolved",
    "turn_end_vote_request",
    "turn_end_vote_resolved",
    "intentional_draw_vote_request",
    "intentional_draw_vote_resolved",
    "intentional_draw",
    "turn_changed",
]);
const arenaRoomLogStore = new Map();
let currentArenaLogRoomId = null;
const arenaChatHistorySeenSeqSetByRoom = new Map();
const preGameGlobalHistorySeenSeqSetByRoom = new Map();
const ARENA_HISTORY_DEBUG_STORAGE_KEY = "quiz_debug_arena_history";
let lastLobbyHistorySignature = "";

/* DEBUG_DIAG_START */
const QUIZ_DIAG_ENABLED = (() => {
    try {
        const params = new URLSearchParams(window.location.search);
        if (params.get("diag") === "1") {
            return true;
        }
        return localStorage.getItem("quiz_diag") === "1";
    } catch {
        return false;
    }
})();
let quizDiagPanelEl = null;
let quizDiagListenersBound = false;

function quizWsReadyStateLabel() {
    if (!ws) return "no-ws";
    const labels = ["CONNECTING", "OPEN", "CLOSING", "CLOSED"];
    return labels[ws.readyState] || String(ws.readyState);
}

function ensureQuizDiagPanel() {
    if (!QUIZ_DIAG_ENABLED) return null;
    if (quizDiagPanelEl) return quizDiagPanelEl;

    const panel = document.createElement("div");
    panel.id = "quiz-diag-panel";
    panel.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99999;max-height:36vh;overflow:auto;padding:8px;background:rgba(0,0,0,0.82);color:#7CFC00;font:12px/1.4 monospace;white-space:pre-wrap;word-break:break-word;";

    const title = document.createElement("div");
    title.style.cssText = "font-weight:700;color:#fff;margin-bottom:6px;";
    title.textContent = "QUIZ DIAG (temporary)";
    panel.appendChild(title);

    document.body.appendChild(panel);
    quizDiagPanelEl = panel;
    return panel;
}

function diagLog(message, details = null) {
    if (!QUIZ_DIAG_ENABLED) return;
    const now = new Date();
    const timestamp = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}.${String(now.getMilliseconds()).padStart(3, "0")}`;
    const suffix = details && typeof details === "object" ? ` ${JSON.stringify(details)}` : "";
    const line = `[${timestamp}] ${message}${suffix}`;

    console.info("[quiz-diag]", line);

    if (document.body) {
        const panel = ensureQuizDiagPanel();
        if (panel) {
            const row = document.createElement("div");
            row.textContent = line;
            panel.appendChild(row);
            while (panel.childElementCount > 120) {
                panel.removeChild(panel.children[1]);
            }
            panel.scrollTop = panel.scrollHeight;
        }
    }
}

function bindDiagLifecycleListeners() {
    if (!QUIZ_DIAG_ENABLED || quizDiagListenersBound) {
        return;
    }

    quizDiagListenersBound = true;
    document.addEventListener("visibilitychange", () => {
        diagLog("visibilitychange", {
            visibility: document.visibilityState,
            ws: quizWsReadyStateLabel(),
            online: navigator.onLine,
        });
    });

    window.addEventListener("online", () => {
        diagLog("network_online", { ws: quizWsReadyStateLabel() });
    });

    window.addEventListener("offline", () => {
        diagLog("network_offline", { ws: quizWsReadyStateLabel() });
    });
}

bindDiagLifecycleListeners();
/* DEBUG_DIAG_END */

function isArenaHistoryDebugEnabled() {
    const runtimeFlag = typeof window !== "undefined" && window.__QUIZ_DEBUG_ARENA_HISTORY__ === true;
    if (runtimeFlag) {
        return true;
    }

    try {
        return localStorage.getItem(ARENA_HISTORY_DEBUG_STORAGE_KEY) === "1";
    } catch {
        return false;
    }
}

function debugArenaHistory(message, details = null) {
    if (!isArenaHistoryDebugEnabled()) {
        return;
    }

    if (details && typeof details === "object") {
        console.info("[arena-history]", message, details);
        return;
    }

    console.info("[arena-history]", message);
}

function isPlayerRole(role = userRole) {
    return role === "team-left" || role === "team-right";
}

function getRoleDisplayLabel(role) {
    const normalizedRole = String(role || "").trim();
    const labels = {
        questioner: "出題者",
        "team-left": "参加者",
        "team-right": "参加者",
        spectator: "観戦者",
    };

    return labels[normalizedRole] || normalizedRole || "-";
}

function formatAiModelTime(timeValue) {
    const numericTime = Number(timeValue);
    if (!Number.isFinite(numericTime) || numericTime <= 0) {
        return "";
    }

    return `生成時間目安:${Math.trunc(numericTime)}秒`;
}

function formatAiModelDisplayText(model) {
    if (!model) {
        return "";
    }

    const label = String(model.label || model.id || "").trim();
    const timeText = formatAiModelTime(model.time);
    if (!label) {
        return timeText;
    }

    return timeText ? `${label} (${timeText})` : label;
}

function getAiModelDisplayText(modelId) {
    const normalizedModelId = String(modelId || "").trim();
    if (!normalizedModelId) {
        return "未設定";
    }

    const model = aiModelOptionsById.get(normalizedModelId);
    if (!model) {
        return normalizedModelId;
    }

    return formatAiModelDisplayText(model) || normalizedModelId;
}

function populateAiModelSelect() {
    if (!aiModelSelectEl) {
        return;
    }

    aiModelSelectEl.innerHTML = "";

    aiModelOptions.forEach((model) => {
        const option = document.createElement("option");
        option.value = model.id;
        option.textContent = formatAiModelDisplayText(model) || model.id;
        aiModelSelectEl.appendChild(option);
    });
}

async function loadAiModelOptions() {
    if (aiModelsLoaded) {
        diagLog("api_ai_models_cache_hit");
        return true;
    }

    let response = null;
    let responseBodyText = "";
    try {
        diagLog("api_ai_models_start", { ws: quizWsReadyStateLabel() });
        response = await fetch("/api/ai-models", buildJsonApiFetchInit());
        diagLog("api_ai_models_response", { status: response.status, ok: response.ok });
        if (!response.ok) {
            throw new Error(`failed_to_fetch_ai_models:${response.status}`);
        }

        responseBodyText = await response.text();
        if (responseBodyText.trim().startsWith("<!DOCTYPE html") || responseBodyText.trim().startsWith("<html")) {
            throw new Error("failed_to_parse_ai_models_json:html_response_received");
        }
        let payload = null;
        try {
            payload = JSON.parse(responseBodyText);
        } catch (parseError) {
            const parseMessage = String(parseError?.message || parseError || "unknown").trim();
            throw new Error(`failed_to_parse_ai_models_json:${parseMessage}`);
        }
        const models = Array.isArray(payload?.models) ? payload.models : [];

        const normalizedOptions = models
            .map((model) => {
                const modelId = String(model?.id || "").trim();
                const apiModel = String(model?.model || modelId).trim();
                const label = String(model?.label || modelId).trim();
                const time = Number(model?.time || 0);
                if (!modelId) return null;
                return {
                    id: modelId,
                    model: apiModel,
                    label,
                    time: Number.isFinite(time) && time > 0 ? Math.trunc(time) : null,
                    provider: String(model?.provider || "").trim().toLowerCase(),
                    reasoning: String(model?.reasoning || "").trim().toLowerCase() || null,
                };
            })
            .filter(Boolean);

        if (normalizedOptions.length > 0) {
            aiModelOptions = normalizedOptions;
            aiModelOptionsById = new Map(normalizedOptions.map((item) => [item.id, item]));
            const defaultFromApi = String(payload?.default_model_id || "").trim();
            const allIds = new Set(normalizedOptions.map((item) => item.id));
            defaultAiModelId = allIds.has(defaultFromApi) ? defaultFromApi : normalizedOptions[0].id;
            aiModelsLoaded = true;
            diagLog("api_ai_models_success", { model_count: normalizedOptions.length });
            return true;
        }

        throw new Error("empty_ai_model_options");
    } catch (error) {
        console.warn("AIモデル一覧の取得に失敗しました", error);
        diagLog("api_ai_models_failed", {
            error: String(error?.message || error || "unknown"),
            name: String(error?.name || ""),
            stack: String(error?.stack || ""),
            status: Number(response?.status || 0) || null,
            body_head: responseBodyText ? String(responseBodyText).slice(0, 300) : null,
            ua: String(navigator?.userAgent || ""),
            ws: quizWsReadyStateLabel(),
        });
        aiModelsLoaded = false;
        return false;
    }
}

function normalizeAiAccuracyRate(rawValue) {
    const numericValue = Number(rawValue);
    if (!Number.isFinite(numericValue)) {
        return DEFAULT_AI_ACCURACY_RATE;
    }

    const clampedValue = Math.max(MIN_AI_ACCURACY_RATE, Math.min(100, numericValue));
    if (clampedValue <= 5 && Number.isInteger(clampedValue)) {
        return Math.max(MIN_AI_ACCURACY_RATE, Math.min(100, clampedValue * 20));
    }

    return Math.max(MIN_AI_ACCURACY_RATE, Math.min(100, Math.round(clampedValue / 10) * 10));
}

function updateAiAccuracyRateDisplay(rawValue) {
    if (!aiAccuracyRateValueEl) {
        return;
    }

    aiAccuracyRateValueEl.textContent = `${normalizeAiAccuracyRate(rawValue)}%`;
}

function initializeAiAccuracyRateControl() {
    if (!aiAccuracyRateRangeEl) {
        return;
    }

    aiAccuracyRateRangeEl.min = String(MIN_AI_ACCURACY_RATE);
    aiAccuracyRateRangeEl.max = "100";
    aiAccuracyRateRangeEl.step = "10";
    aiAccuracyRateRangeEl.value = String(DEFAULT_AI_ACCURACY_RATE);
    updateAiAccuracyRateDisplay(aiAccuracyRateRangeEl.value);
}

function updateAiQuestionButtonState(rooms = currentRoomsSnapshot) {
    const hasActiveAiRoom = Array.isArray(rooms) && rooms.some((room) => Boolean(room?.is_ai_room));
    const shouldDisable = aiQuestionRequestPending || aiQuestionGenerationActive || hasActiveAiRoom;

    if (aiQuestionBtnEl) {
        aiQuestionBtnEl.disabled = shouldDisable;
        aiQuestionBtnEl.setAttribute("aria-busy", aiQuestionRequestPending ? "true" : "false");

        if (aiQuestionRequestPending) {
            aiQuestionBtnEl.title = "AI出題を送信中です";
        } else if (aiQuestionGenerationActive) {
            aiQuestionBtnEl.title = String(aiQuestionGenerationOwnerId || "") === String(myClientId || "")
                ? "AI問題を生成中です"
                : "他のAI問題を生成中です";
        } else if (hasActiveAiRoom) {
            aiQuestionBtnEl.title = "AI出題部屋があるため使用できません";
        } else {
            aiQuestionBtnEl.title = "";
        }
    }
}

function isGameGlobalLog(logEl) {
    return Boolean(logEl) && logEl.id === "game-chat-log-game-global";
}

function isTeamLeftRevealWindow() {
    return isInGameArena()
        && (currentRoomGameState || "waiting") === "playing"
        && userRole === "team-left"
        && Boolean(currentGameState?.left_correct_waiting);
}

function shouldLockGlobalLogFilter(logEl) {
    if (isTeamLeftRevealWindow()) {
        return false;
    }

    return isGameGlobalLog(logEl)
        && isInGameArena()
        && (currentRoomGameState || "waiting") === "playing"
        && isPlayerRole();
}

function enforceChatLogFilterLockIfNeeded(logEl) {
    const filterState = getChatLogFilterState(logEl);
    if (shouldLockGlobalLogFilter(logEl)) {
        filterState.showChat = false;
        filterState.showLog = true;
    }
    return filterState;
}

function getChatLogFilterState(logEl) {
    const key = String(logEl?.id || "").trim();
    if (key === "") {
        return { showChat: true, showLog: true };
    }

    let state = chatLogFilterStateById.get(key);
    if (!state) {
        state = { showChat: true, showLog: true };
        chatLogFilterStateById.set(key, state);
    }
    return state;
}

function isChatEventItem(itemEl) {
    return itemEl.classList.contains("is-chat-event") || itemEl.dataset.eventType === "chat";
}

function applyChatLogFilterToItem(itemEl, filterState) {
    if (!itemEl || !filterState) return;

    const isChat = isChatEventItem(itemEl);
    const shouldHide = (isChat && !filterState.showChat)
        || (!isChat && !filterState.showLog);
    itemEl.classList.toggle("filtered-out", shouldHide);
}

function applyChatLogFilters(logEl) {
    if (!logEl) return;

    const filterState = enforceChatLogFilterLockIfNeeded(logEl);
    logEl.querySelectorAll(".event-log-item").forEach((itemEl) => {
        applyChatLogFilterToItem(itemEl, filterState);
    });
}

function updateChatLogFilterButtonLabel(buttonEl, prefix, enabled) {
    if (!buttonEl) return;
    buttonEl.textContent = `${prefix}:${enabled ? "ON" : "OFF"}`;
    buttonEl.setAttribute("aria-pressed", enabled ? "true" : "false");
}

function attachChatLogFilterControls(chatBoxEl) {
    if (!chatBoxEl) return;

    const titleEl = chatBoxEl.querySelector(".arena-chat-title");
    const logEl = chatBoxEl.querySelector(".chat-log");
    if (!titleEl || !logEl) return;
    if (titleEl.querySelector(".chat-log-filter-tools")) return;

    const closeBtnEl = titleEl.querySelector("#arena-logs-close-btn");
    const titleTextSourceEl = Array.from(titleEl.children).find((child) => child !== closeBtnEl);
    const titleText = String(titleTextSourceEl?.textContent || titleEl.textContent || "").replace("×", "").trim();
    titleEl.textContent = "";

    const textEl = document.createElement("span");
    textEl.className = "arena-chat-title-text";
    textEl.textContent = titleText;

    const toolsEl = document.createElement("div");
    toolsEl.className = "chat-log-filter-tools";

    const chatFilterBtn = document.createElement("button");
    chatFilterBtn.type = "button";
    chatFilterBtn.className = "chat-log-filter-btn";
    chatFilterBtn.setAttribute("aria-label", "チャット表示切り替え");

    const logFilterBtn = document.createElement("button");
    logFilterBtn.type = "button";
    logFilterBtn.className = "chat-log-filter-btn";
    logFilterBtn.setAttribute("aria-label", "ログ表示切り替え");

    const renderButtons = () => {
        const state = enforceChatLogFilterLockIfNeeded(logEl);
        const isLocked = shouldLockGlobalLogFilter(logEl);
        updateChatLogFilterButtonLabel(chatFilterBtn, "Chat", state.showChat);
        updateChatLogFilterButtonLabel(logFilterBtn, "Log", state.showLog);
        chatFilterBtn.disabled = isLocked;
        logFilterBtn.disabled = isLocked;
        chatFilterBtn.setAttribute("aria-disabled", String(isLocked));
        logFilterBtn.setAttribute("aria-disabled", String(isLocked));
    };

    chatFilterBtn.addEventListener("click", () => {
        if (shouldLockGlobalLogFilter(logEl)) {
            return;
        }
        const state = getChatLogFilterState(logEl);
        state.showChat = !state.showChat;
        applyChatLogFilters(logEl);
        renderButtons();
    });

    logFilterBtn.addEventListener("click", () => {
        if (shouldLockGlobalLogFilter(logEl)) {
            return;
        }
        const state = getChatLogFilterState(logEl);
        state.showLog = !state.showLog;
        applyChatLogFilters(logEl);
        renderButtons();
    });

    toolsEl.appendChild(chatFilterBtn);
    toolsEl.appendChild(logFilterBtn);
    titleEl.appendChild(textEl);
    titleEl.appendChild(toolsEl);
    if (closeBtnEl) {
        titleEl.appendChild(closeBtnEl);
    }

    chatLogFilterControlById.set(logEl.id, {
        logEl,
        renderButtons,
    });

    renderButtons();
    applyChatLogFilters(logEl);
}

function initChatLogFilterControls() {
    document.querySelectorAll('.chat-box[data-chat-room="game"]').forEach((chatBoxEl) => {
        attachChatLogFilterControls(chatBoxEl);
    });
}

function refreshChatLogFilterControls() {
    chatLogFilterControlById.forEach(({ logEl, renderButtons }) => {
        enforceChatLogFilterLockIfNeeded(logEl);
        applyChatLogFilters(logEl);
        renderButtons();
    });
}

function enableArenaProgressChatFilter() {
    const globalLogEl = document.getElementById("game-chat-log-game-global");
    if (!globalLogEl) {
        return;
    }

    const state = getChatLogFilterState(globalLogEl);
    state.showChat = true;
    state.showLog = true;
    applyChatLogFilters(globalLogEl);

    const controls = chatLogFilterControlById.get(globalLogEl.id);
    if (controls) {
        controls.renderButtons();
    }
}

function getOrCreateArenaRoomLogState(roomOwnerId) {
    const roomId = String(roomOwnerId || "").trim();
    if (roomId === "") return null;

    let state = arenaRoomLogStore.get(roomId);
    if (!state) {
        state = {
            "team-left": [],
            "team-right": [],
            "game-global": [],
        };
        arenaRoomLogStore.set(roomId, state);
    }
    return state;
}

function compareArenaLogOrder(aTimestamp, aVersion, bTimestamp, bVersion) {
    const aTs = Number(aTimestamp || 0);
    const bTs = Number(bTimestamp || 0);
    const hasATs = Number.isFinite(aTs) && aTs > 0;
    const hasBTs = Number.isFinite(bTs) && bTs > 0;

    if (hasATs && hasBTs && aTs !== bTs) {
        return aTs - bTs;
    }

    const aVer = Math.max(0, Number(aVersion || 0));
    const bVer = Math.max(0, Number(bVersion || 0));
    if (aVer !== bVer) {
        return aVer - bVer;
    }

    return 0;
}

function resolveReplacementEventTimestamp(existingTimestamp, incomingTimestamp) {
    const existingTs = Number(existingTimestamp || 0);
    const incomingTs = Number(incomingTimestamp || 0);
    const hasExistingTs = Number.isFinite(existingTs) && existingTs > 0;
    const hasIncomingTs = Number.isFinite(incomingTs) && incomingTs > 0;

    if (!hasExistingTs && !hasIncomingTs) {
        return null;
    }
    if (!hasExistingTs) {
        return Math.floor(incomingTs);
    }
    if (!hasIncomingTs) {
        return Math.floor(existingTs);
    }

    // Replacement updates should not push the original log forward in time.
    return Math.floor(Math.min(existingTs, incomingTs));
}

function insertArenaLogInOrder(logs, entry) {
    if (!Array.isArray(logs)) {
        return;
    }

    let insertIndex = logs.length;
    for (let i = logs.length - 1; i >= 0; i -= 1) {
        const candidate = logs[i] || {};
        const order = compareArenaLogOrder(
            candidate.eventTimestamp,
            candidate.eventVersion,
            entry?.eventTimestamp,
            entry?.eventVersion,
        );
        if (order <= 0) {
            break;
        }
        insertIndex = i;
    }

    if (insertIndex < logs.length) {
        logs.splice(insertIndex, 0, entry);
    } else {
        logs.push(entry);
    }

    while (logs.length > 50) {
        logs.shift();
    }
}

function pushArenaRoomLog(
    roomOwnerId,
    chatType,
    eventType,
    eventMessage,
    eventTimestamp = null,
    logMarkerId = null,
    eventId = null,
    eventRevision = 1,
    eventVersion = 0,
) {
    const state = getOrCreateArenaRoomLogState(roomOwnerId);
    if (!state || !ARENA_CHAT_TYPES.includes(chatType)) {
        return;
    }

    const logs = state[chatType];

    if (eventId) {
        const existingIndex = logs.findIndex((log) => log.eventId === eventId);
        if (existingIndex !== -1) {
            const currentRevision = Number(logs[existingIndex]?.eventRevision || 1);
            const nextRevision = Math.max(1, Number(eventRevision || 1));
            if (nextRevision >= currentRevision) {
                const existingLog = logs[existingIndex] || {};
                logs.splice(existingIndex, 1);
                insertArenaLogInOrder(logs, {
                    eventType,
                    eventMessage,
                    eventTimestamp: resolveReplacementEventTimestamp(existingLog?.eventTimestamp, eventTimestamp),
                    logMarkerId,
                    eventId,
                    eventRevision: nextRevision,
                    eventVersion: Math.max(0, Number(eventVersion || existingLog?.eventVersion || 0)),
                });
            }
            return;
        }
    }

    // If logMarkerId is provided and there's an existing log with the same marker, replace it
    if (logMarkerId) {
        const existingIndex = logs.findIndex(log => log.logMarkerId === logMarkerId);
        if (existingIndex !== -1) {
            const existingLog = logs[existingIndex] || {};
            logs.splice(existingIndex, 1);
            insertArenaLogInOrder(logs, {
                eventType,
                eventMessage,
                eventTimestamp: resolveReplacementEventTimestamp(existingLog?.eventTimestamp, eventTimestamp),
                logMarkerId,
                eventId: eventId || existingLog?.eventId || null,
                eventRevision: Math.max(1, Number(eventRevision || existingLog?.eventRevision || 1)),
                eventVersion: Math.max(0, Number(eventVersion || existingLog?.eventVersion || 0)),
            });
            return;
        }
    }

    insertArenaLogInOrder(logs, {
        eventType,
        eventMessage,
        eventTimestamp,
        logMarkerId,
        eventId,
        eventRevision: Math.max(1, Number(eventRevision || 1)),
        eventVersion: Math.max(0, Number(eventVersion || 0)),
    });
}

function upsertHydratedArenaLog(
    roomStateLogs,
    chatType,
    eventType,
    eventMessage,
    eventTimestamp,
    logMarkerId = null,
    eventId = null,
    eventRevision = 1,
    eventVersion = 0,
) {
    const logs = roomStateLogs[chatType];
    if (!Array.isArray(logs)) {
        return;
    }

    if (eventId) {
        const existingIndex = logs.findIndex((log) => log.eventId === eventId);
        if (existingIndex !== -1) {
            const currentRevision = Number(logs[existingIndex]?.eventRevision || 1);
            const nextRevision = Math.max(1, Number(eventRevision || 1));
            if (nextRevision >= currentRevision) {
                const existingLog = logs[existingIndex] || {};
                logs.splice(existingIndex, 1);
                insertArenaLogInOrder(logs, {
                    eventType,
                    eventMessage,
                    eventTimestamp: resolveReplacementEventTimestamp(existingLog?.eventTimestamp, eventTimestamp),
                    logMarkerId,
                    eventId,
                    eventRevision: nextRevision,
                    eventVersion: Math.max(0, Number(eventVersion || existingLog?.eventVersion || 0)),
                });
            }
            return;
        }
    }

    if (logMarkerId) {
        const existingIndex = logs.findIndex((log) => log.logMarkerId === logMarkerId);
        if (existingIndex !== -1) {
            const existingLog = logs[existingIndex] || {};
            logs.splice(existingIndex, 1);
            insertArenaLogInOrder(logs, {
                eventType,
                eventMessage,
                eventTimestamp: resolveReplacementEventTimestamp(existingLog?.eventTimestamp, eventTimestamp),
                logMarkerId,
                eventId: eventId || existingLog?.eventId || null,
                eventRevision: Math.max(1, Number(eventRevision || existingLog?.eventRevision || 1)),
                eventVersion: Math.max(0, Number(eventVersion || existingLog?.eventVersion || 0)),
            });
            return;
        }
    }

    insertArenaLogInOrder(logs, {
        eventType,
        eventMessage,
        eventTimestamp,
        logMarkerId,
        eventId,
        eventRevision: Math.max(1, Number(eventRevision || 1)),
        eventVersion: Math.max(0, Number(eventVersion || 0)),
    });
}

function normalizeLogMarkerId(rawValue) {
    const marker = String(rawValue || "").trim();
    if (marker === "") {
        return null;
    }

    const lower = marker.toLowerCase();
    if (lower === "none" || lower === "null" || lower === "undefined") {
        return null;
    }

    return marker;
}

function normalizeEventId(rawValue) {
    const eventId = String(rawValue || "").trim();
    if (eventId === "") {
        return null;
    }

    const lower = eventId.toLowerCase();
    if (lower === "none" || lower === "null" || lower === "undefined") {
        return null;
    }

    return eventId;
}

function normalizeArenaEventRecord(rawRecord) {
    const eventType = String(rawRecord?.event_type || rawRecord?.event_kind || "").trim();
    const eventChatType = String(rawRecord?.event_chat_type || rawRecord?.event_scope || "").trim();
    const eventMessage = String(rawRecord?.event_view?.display_message || rawRecord?.event_message || rawRecord?.message || "").trim();
    const eventTimestamp = Number(rawRecord?.event_timestamp || rawRecord?.timestamp || 0);
    const eventId = normalizeEventId(rawRecord?.event_id || rawRecord?.event_payload?.event_id);
    const eventRevision = Math.max(1, Number(rawRecord?.event_revision || rawRecord?.event_payload?.event_revision || 1));
    const eventVersion = Math.max(0, Number(rawRecord?.event_version || rawRecord?.event_payload?.event_version || 0));
    const logMarkerId = normalizeLogMarkerId(rawRecord?.log_marker_id || rawRecord?.event_payload?.log_marker_id || rawRecord?.event_payload?.vote_id);

    return {
        eventType,
        eventChatType,
        eventMessage,
        eventTimestamp,
        eventId,
        eventRevision,
        eventVersion,
        logMarkerId,
        roomId: String(rawRecord?.event_room_id || rawRecord?.room_owner_id || currentRoomSnapshot?.room_owner_id || "").trim(),
    };
}

function shouldDuplicateOpenResolvedToBothTeamLogs(record) {
    if (!record) {
        return false;
    }

    return record.eventType === "open_vote_resolved"
        && (record.eventChatType === "team-left" || record.eventChatType === "team-right")
        && String(record.eventMessage || "").trim() !== "";
}

function shouldMirrorArenaEventToGlobal(record, viewerRole = userRole) {
    if (!record || !record.eventChatType) {
        return false;
    }

    if (record.eventType === "turn_changed") {
        return false;
    }

    const isTeamLog = record.eventChatType === "team-left" || record.eventChatType === "team-right";
    return isTeamLog
        && record.eventType !== "chat"
        && (
            ARENA_VOTE_EVENT_TYPES.has(record.eventType)
            || (
                (viewerRole === "team-left" || viewerRole === "team-right")
                && record.eventChatType === viewerRole
            )
            || (
                !isPlayerRole(viewerRole)
                && record.eventChatType === "team-left"
            )
        );
}

function getArenaDisplayedMessageForViewer(record, viewerRole = userRole) {
    if (!record) {
        return "";
    }

    return record.eventMessage;
}

function clearArenaLogElements() {
    ARENA_CHAT_TYPES.forEach((chatType) => {
        const logEl = document.getElementById(`game-chat-log-${chatType}`);
        if (!logEl) return;
        logEl.innerHTML = "";

        const scrollContainer = resolveLogScrollContainer(logEl);
        const indicatorEl = ensureLogNewIndicator(scrollContainer);
        if (indicatorEl) {
            indicatorEl.classList.add("hidden");
        }
    });
}

function renderArenaLogsForRoom(roomOwnerId, options = {}) {
    const roomId = String(roomOwnerId || "").trim();
    const forceScrollToBottom = options?.forceScrollToBottom === true;
    currentArenaLogRoomId = roomId || null;

    const scrollStateByChatType = new Map();
    ARENA_CHAT_TYPES.forEach((chatType) => {
        const logEl = document.getElementById(`game-chat-log-${chatType}`);
        if (!logEl) return;

        const scrollContainer = resolveLogScrollContainer(logEl);
        if (!scrollContainer) return;

        const wasNearBottom = isLogNearBottom(scrollContainer);
        const distanceFromBottom = Math.max(
            0,
            scrollContainer.scrollHeight - (scrollContainer.scrollTop + scrollContainer.clientHeight)
        );

        scrollStateByChatType.set(chatType, {
            wasNearBottom,
            distanceFromBottom,
        });
    });

    clearArenaLogElements();
    if (roomId === "") {
        return;
    }

    const state = getOrCreateArenaRoomLogState(roomId);
    if (!state) {
        return;
    }

    ARENA_CHAT_TYPES.forEach((chatType) => {
        const logEl = document.getElementById(`game-chat-log-${chatType}`);
        if (!logEl) return;

        const entries = state[chatType] || [];
        let addedCount = 0;
        entries.forEach(({ eventType, eventMessage, eventTimestamp, logMarkerId, eventId, eventRevision, eventVersion }) => {
            const item = createEventLogItem(eventType, eventMessage, eventTimestamp, logMarkerId, eventId, eventRevision, eventVersion);
            if (item) {
                logEl.appendChild(item);
                applyChatLogFilterToItem(item, getChatLogFilterState(logEl));
                addedCount += 1;
            }
        });

        debugArenaHistory(`renderArenaLogsForRoom: ${chatType}`, {
            storeCount: entries.length,
            addedToDOMCount: addedCount,
            domElementCount: logEl.querySelectorAll(".event-log-item").length,
            visibleCount: logEl.querySelectorAll(".event-log-item:not(.filtered-out)").length,
        });

        const scrollContainer = resolveLogScrollContainer(logEl);
        if (scrollContainer) {
            const indicatorEl = ensureLogNewIndicator(scrollContainer);

            const prevScrollState = scrollStateByChatType.get(chatType);
            const shouldSnapToBottom = forceScrollToBottom || Boolean(prevScrollState?.wasNearBottom);
            if (shouldSnapToBottom) {
                scrollContainer.scrollTop = scrollContainer.scrollHeight;
                if (indicatorEl) {
                    indicatorEl.classList.add("hidden");
                }
                return;
            }

            const distanceFromBottom = Math.max(0, Number(prevScrollState?.distanceFromBottom || 0));
            scrollContainer.scrollTop = Math.max(
                0,
                scrollContainer.scrollHeight - scrollContainer.clientHeight - distanceFromBottom
            );
            if (indicatorEl) {
                indicatorEl.classList.remove("hidden");
            }
        }
    });
}

function hydrateArenaChatHistoryIfNeeded(currentRoom) {
    if (!currentRoom) {
        return;
    }

    const roomId = String(currentRoom.room_owner_id || "").trim();
    if (roomId === "") {
        return;
    }

    const history = Array.isArray(currentRoom.arena_chat_history)
        ? currentRoom.arena_chat_history
        : [];
    const roomStateLogs = getOrCreateArenaRoomLogState(roomId);
    if (!roomStateLogs) {
        return;
    }

    roomStateLogs["team-left"] = [];
    roomStateLogs["team-right"] = [];
    roomStateLogs["game-global"] = [];

    const seenSeqSet = new Set();
    arenaChatHistorySeenSeqSetByRoom.set(roomId, seenSeqSet);

    const incomingChatTypeCount = { "team-left": 0, "team-right": 0, "game-global": 0, "other": 0 };
    history.forEach((entry) => {
        const type = String(entry?.event_chat_type || "").trim() || "other";
        incomingChatTypeCount[type] = (incomingChatTypeCount[type] || 0) + 1;
    });
    debugArenaHistory("hydrateArenaChatHistoryIfNeeded incoming data", {
        roomId,
        totalIncoming: history.length,
        chatTypeDistribution: incomingChatTypeCount,
    });

    const sortedHistory = [...history].sort((a, b) => {
        const timeDiff = Number(a?.timestamp || 0) - Number(b?.timestamp || 0);
        if (timeDiff !== 0) {
            return timeDiff;
        }
        return Number(a?.seq || 0) - Number(b?.seq || 0);
    });

    let acceptedCount = 0;
    let skippedInvalidCount = 0;
    let skippedChatTypeCount = 0;
    let mirroredCount = 0;

    sortedHistory.forEach((entry) => {
        const seq = Number(entry?.seq || 0);
        const record = normalizeArenaEventRecord(entry);
        if (!Number.isFinite(seq) || seenSeqSet.has(seq) || record.eventMessage === "" || record.eventType === "") {
            skippedInvalidCount += 1;
            return;
        }
        if (HIDDEN_ARENA_EVENT_TYPES.has(record.eventType)) {
            return;
        }
        if (!ARENA_CHAT_TYPES.includes(record.eventChatType)) {
            skippedChatTypeCount += 1;
            return;
        }

        const eventMessage = getArenaDisplayedMessageForViewer(record);
        upsertHydratedArenaLog(
            roomStateLogs,
            record.eventChatType,
            record.eventType,
            eventMessage,
            record.eventTimestamp,
            record.logMarkerId,
            record.eventId,
            record.eventRevision,
            record.eventVersion,
        );

        if (shouldDuplicateOpenResolvedToBothTeamLogs(record)) {
            const oppositeChatType = record.eventChatType === "team-left" ? "team-right" : "team-left";
            upsertHydratedArenaLog(
                roomStateLogs,
                oppositeChatType,
                record.eventType,
                eventMessage,
                record.eventTimestamp,
                record.logMarkerId,
                record.eventId,
                record.eventRevision,
                record.eventVersion,
            );
        }

        const shouldMirrorToGlobal = shouldMirrorArenaEventToGlobal(record);
        if (shouldMirrorToGlobal) {
            upsertHydratedArenaLog(
                roomStateLogs,
                "game-global",
                record.eventType,
                eventMessage,
                record.eventTimestamp,
                record.logMarkerId,
                record.eventId,
                record.eventRevision,
                record.eventVersion,
            );
            mirroredCount += 1;
        }

        seenSeqSet.add(seq);
        acceptedCount += 1;
    });

    debugArenaHistory("hydrateArenaChatHistoryIfNeeded", {
        roomId,
        incomingHistoryCount: sortedHistory.length,
        acceptedCount,
        mirroredCount,
        skippedInvalidCount,
        skippedChatTypeCount,
        teamLeftCount: roomStateLogs["team-left"].length,
        teamRightCount: roomStateLogs["team-right"].length,
        globalCount: roomStateLogs["game-global"].length,
    });

}

function hydratePreGameGlobalHistoryIfNeeded(currentRoom) {
    if (!currentRoom || currentRoom.role !== "participant") {
        return;
    }

    if (String(currentRoom.game_state || "") !== "playing") {
        return;
    }

    const roomId = String(currentRoom.room_owner_id || "").trim();
    if (roomId === "") {
        return;
    }

    const history = Array.isArray(currentRoom.pre_game_global_chat_history)
        ? currentRoom.pre_game_global_chat_history
        : [];
    if (history.length === 0) {
        return;
    }

    const roomStateLogs = getOrCreateArenaRoomLogState(roomId);
    if (!roomStateLogs) {
        return;
    }

    let seenSeqSet = preGameGlobalHistorySeenSeqSetByRoom.get(roomId);
    if (!seenSeqSet) {
        seenSeqSet = new Set();
        preGameGlobalHistorySeenSeqSetByRoom.set(roomId, seenSeqSet);
    }
    let updated = false;

    const sortedHistory = [...history].sort((a, b) => {
        const timeDiff = Number(a?.timestamp || 0) - Number(b?.timestamp || 0);
        if (timeDiff !== 0) {
            return timeDiff;
        }
        return Number(a?.seq || 0) - Number(b?.seq || 0);
    });

    sortedHistory.forEach((entry) => {
        const seq = Number(entry?.seq || 0);
        const eventType = String(entry?.event_type || "chat").trim() || "chat";
        let eventMessage = String(entry?.event_message || "").trim();
        const eventTimestamp = Number(entry?.timestamp || 0);
        const eventId = normalizeEventId(entry?.event_id);
        const eventRevision = Math.max(1, Number(entry?.event_revision || 1));
        const eventVersion = Math.max(0, Number(entry?.event_version || 0));
        const logMarkerId = normalizeLogMarkerId(entry?.log_marker_id);

        if (!Number.isFinite(seq) || seenSeqSet.has(seq) || eventMessage === "") {
            return;
        }

        // Hide answer text for opponent players in answer vote logs
        if ((eventType === "answer_vote_request" || eventType === "answer_vote_resolved")
            && isPlayerRole()) {
            eventMessage = eventMessage.replace(/が「[^」]*」と/, "が");
        }

        upsertHydratedArenaLog(
            roomStateLogs,
            "game-global",
            eventType,
            eventMessage,
            eventTimestamp,
            logMarkerId,
            eventId,
            eventRevision,
            eventVersion,
        );

        seenSeqSet.add(seq);
        updated = true;
    });

    if (updated && currentArenaLogRoomId === roomId) {
        renderArenaLogsForRoom(roomId);
    }
}

function resetArenaChatCaches() {
    arenaRoomLogStore.clear();
    arenaChatHistorySeenSeqSetByRoom.clear();
    preGameGlobalHistorySeenSeqSetByRoom.clear();
    handledOpenVoteIds.clear();
    handledAnswerVoteIds.clear();
    handledTurnEndVoteIds.clear();
    handledIntentionalDrawVoteIds.clear();
    currentArenaLogRoomId = null;
    clearArenaLogElements();
}

function resolveLogScrollContainer(logEl) {
    if (!logEl) return null;
    return logEl.id === "event-log"
        ? (logEl.parentElement || logEl)
        : logEl;
}

function isLogNearBottom(scrollContainer) {
    if (!scrollContainer) return true;

    const remaining = scrollContainer.scrollHeight - (scrollContainer.scrollTop + scrollContainer.clientHeight);
    return remaining <= LOG_AUTO_SCROLL_THRESHOLD_PX;
}

function ensureLogNewIndicator(scrollContainer) {
    if (!scrollContainer) return null;

    let indicatorEl = logNewIndicatorMap.get(scrollContainer);
    if (!indicatorEl) {
        indicatorEl = document.createElement("button");
        indicatorEl.type = "button";
        indicatorEl.className = "new-log-indicator hidden";
        indicatorEl.textContent = "新規";
        indicatorEl.setAttribute("aria-label", "最新メッセージへ移動");

        indicatorEl.addEventListener("click", () => {
            scrollContainer.scrollTop = scrollContainer.scrollHeight;
            indicatorEl.classList.add("hidden");
        });

        const hostCandidate = scrollContainer.parentElement;
        const host = hostCandidate && hostCandidate.classList.contains("log-scroll-shell")
            ? hostCandidate
            : scrollContainer;
        host.appendChild(indicatorEl);
        logNewIndicatorMap.set(scrollContainer, indicatorEl);
    }

    if (!logScrollListenerBound.has(scrollContainer)) {
        scrollContainer.addEventListener("scroll", () => {
            if (isLogNearBottom(scrollContainer)) {
                const btn = logNewIndicatorMap.get(scrollContainer);
                if (btn) {
                    btn.classList.add("hidden");
                }
            }
        });
        logScrollListenerBound.add(scrollContainer);
    }

    return indicatorEl;
}

function getOrCreatePersistentClientId() {
    const storageKey = "quiz_client_id";
    let clientId = String(localStorage.getItem(storageKey) || "").trim();
    if (clientId !== "") {
        return clientId;
    }

    clientId = crypto.randomUUID();
    localStorage.setItem(storageKey, clientId);
    return clientId;
}

async function showConnectionTimeoutReloadModal() {
    if (connectionTimeoutModalShown) return;
    connectionTimeoutModalShown = true;

    closeAllModals();
    await showConfirmModal(
        "接続がタイムアウトしました。\n\nページを再読み込みしてください。",
        {
            hideCancel: true,
            okLabel: "ページを再読み込み",
        }
    );

    localStorage.setItem("quiz_auto_reconnect", "1");
    window.location.reload();
}

function isLikelyConnectionTimeout(closeEvent) {
    if (!closeEvent) return true;

    const reason = String(closeEvent.reason || "").toLowerCase();
    if (reason.includes("timeout")) return true;

    // 1006: 異常切断, 1011: サーバー側エラーで切断されるケース
    return closeEvent.code === 1006 || closeEvent.code === 1011;
}

function getFriendlyConnectionErrorMessage(closeEvent) {
    if (!closeEvent) {
        return null;
    }

    const reason = String(closeEvent.reason || "").toLowerCase();
    if (reason.includes("duplicate session")) {
        return "このクライアントIDは既に別タブで接続中です。\n\n先に既存タブを閉じるか、既存タブを再読み込みしてください。";
    }
    if (reason.includes("unauthorized")) {
        return "接続認証に失敗しました。\n\nページを再読み込みして再接続してください。";
    }

    return null;
}

function setArenaCharClickGuard() {
    // No-op: モーダル閉鎖後の1クリック破棄はUXを損なうため廃止。
}

function isAnyModalOpen() {
    const judgementModal = document.getElementById("answer-judgement-modal");
    if (confirmModal && confirmModal.open) return true;
    if (alertModal && alertModal.open) return true;
    if (aiQuestionModalEl && aiQuestionModalEl.open) return true;
    if (rulebookModalEl && rulebookModalEl.open) return true;
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

        // 棋譜閲覧画面ではゲーム内チャットボックス（入力フォーム）を非表示
        // ただしログ表示（.event-log）は表示する
        if (isKifuMode && chatRoom === "game") {
            const logEl = chatBox.querySelector(".event-log");
            if (logEl) {
                logEl.classList.remove("hidden");
            }
            // テキストエリアへ hidden を直接付けると復帰時に残留するため、compose単位で隠す。
            setChatBoxEditable(chatBox, false);
            chatBox.classList.remove("hidden");
            return;
        }

        // 過去の不整合で chat-input に hidden が残っていても通常モードで復帰できるよう補正する。
        const inputEl = chatBox.querySelector(".chat-input");
        if (inputEl && inputEl.classList.contains("hidden")) {
            inputEl.classList.remove("hidden");
        }

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

            if (roomState === "finished" && !isGlobalChat) {
                chatBox.classList.remove("hidden");
                setChatBoxEditable(chatBox, false);
                return;
            }

            if (roomState === "playing" && isGlobalChat) {
                const isEditableGlobal = !isPlayerRole() || isTeamLeftRevealWindow();
                setChatBoxEditable(chatBox, isEditableGlobal);
                chatBox.classList.remove("hidden");
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

    refreshChatLogFilterControls();
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
    if (isKifuMode) {
        return false;
    }

    if (chatType === "lobby") {
        return true;
    }

    // 準備中・終了後はアリーナ内の全体チャットのみ全員が送信できる。
    const roomState = currentRoomGameState || "waiting";
    if (chatType === "game-global") {
        if (roomState === "waiting" || roomState === "finished") {
            return true;
        }
        if (roomState === "playing") {
            return userRole === "questioner" || userRole === "spectator" || isTeamLeftRevealWindow();
        }
        return false;
    }

    const sendableRolesByType = {
        "team-left": new Set(["team-left", "questioner"]),
        "team-right": new Set(["team-right", "questioner"]),
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
    if (visibilities.includes(userRole)) {
        return true;
    }

    // 先攻が正解し後攻のアンサー待ち中は、先攻が後攻チャットログを閲覧できるようにする。
    const canSeeOpposingTeamDuringReveal = isTeamLeftRevealWindow()
        && userRole === "team-left"
        && visibilities.includes("team-right");
    return canSeeOpposingTeamDuringReveal;
}

function isInGameArena() {
    return document.getElementById("game-arena-screen").style.display !== "none";
}

function isMobileArenaLogsMode() {
    return window.matchMedia("(max-width: 767px)").matches;
}

function mountArenaLogsIntoModal() {
    if (!arenaGlobalChatBoxEl || !arenaLogsModalSlotEl) return;
    if (arenaGlobalChatBoxEl.parentElement === arenaLogsModalSlotEl) return;
    arenaLogsModalSlotEl.appendChild(arenaGlobalChatBoxEl);
}

function restoreArenaLogsToLayout() {
    const arenaLowerLayoutEl = document.getElementById("arena-lower-layout");
    if (!arenaGlobalChatBoxEl || !arenaLowerLayoutEl) return;
    if (arenaGlobalChatBoxEl.parentElement === arenaLowerLayoutEl) return;
    arenaLowerLayoutEl.appendChild(arenaGlobalChatBoxEl);
}

function closeArenaLogsPresentation(restoreLayout = !isMobileArenaLogsMode()) {
    if (arenaLogsModalEl?.open) {
        arenaLogsModalEl.close();
    }
    if (restoreLayout) {
        restoreArenaLogsToLayout();
    }
}

function syncArenaLogsPresentation() {
    if (!arenaGlobalChatBoxEl) return;

    if (isMobileArenaLogsMode()) {
        mountArenaLogsIntoModal();
        return;
    }

    closeArenaLogsPresentation(true);
}

function canSelectArenaQuestionChars() {
    if (isKifuMode) return false;
    const roomState = currentRoomGameState || "waiting";
    return isInGameArena() && userRole === "questioner" && roomState === "waiting";
}

function isAnswerJudgementPending() {
    return Boolean(currentGameState?.is_judging_answer);
}

function canRequestOpenCharacter() {
    if (isKifuMode) return false;
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;
    if (userRole !== "team-left" && userRole !== "team-right") return false;
    return currentGameState?.current_turn_team === userRole;
}

function canSubmitArenaAnswer() {
    if (isKifuMode) return false;
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;
    if (userRole !== "team-left" && userRole !== "team-right") return false;
    return currentGameState?.current_turn_team === userRole;
}

function canRequestTurnEnd() {
    if (isKifuMode) return false;
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;
    if (userRole !== "team-left" && userRole !== "team-right") return false;
    return currentGameState?.current_turn_team === userRole;
}

function canRequestIntentionalDraw() {
    if (isKifuMode) return false;
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (isAnswerJudgementPending()) return false;

    if (currentRoomSnapshot?.role !== "participant") {
        return false;
    }
    if (!isPlayerRole(userRole)) {
        return false;
    }

    const questionLength = Number(currentRoomSnapshot?.question_length || 0);
    if (!Number.isFinite(questionLength) || questionLength <= 0) {
        return false;
    }

    const openedCount = Array.isArray(currentGameState?.opened_char_indexes)
        ? currentGameState.opened_char_indexes.length
        : 0;
    const openedRatio = openedCount / questionLength;

    const leftWrongCount = Number(currentGameState?.team_left?.wrong_answer_count || 0);
    const rightWrongCount = Number(currentGameState?.team_right?.wrong_answer_count || 0);

    return openedRatio >= 0.7 && leftWrongCount >= 1 && rightWrongCount >= 1;
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

function getCurrentTeamTotalActionPoints() {
    if (userRole === "team-left") {
        const state = currentGameState?.team_left || {};
        return Number(state.action_points || 0) + Number(state.bonus_action_points || 0);
    }

    if (userRole === "team-right") {
        const state = currentGameState?.team_right || {};
        return Number(state.action_points || 0) + Number(state.bonus_action_points || 0);
    }

    return 0;
}

function isRightLastChanceState() {
    return (currentRoomGameState || "waiting") === "playing"
        && userRole === "team-right"
        && currentGameState?.current_turn_team === "team-right"
        && Boolean(currentGameState?.left_correct_waiting);
}

function isRightFinalActionBeforeOpen() {
    return isRightLastChanceState() && getCurrentTeamTotalActionPoints() <= 1;
}

function isRightFinalActionBeforeTurnEnd() {
    return isRightLastChanceState() && getCurrentTeamTotalActionPoints() <= 1;
}

function canViewArenaAnswerForm() {
    if (isKifuMode) return false;
    if (!isInGameArena()) return false;
    if ((currentRoomGameState || "waiting") !== "playing") return false;
    if (currentRoomSnapshot?.role !== "participant") return false;
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
    const canUseIntentionalDraw = canRequestIntentionalDraw();
    const answerComposeEl = arenaAnswerInputEl.closest(".arena-answer-compose");
    const shouldShowBox = canView || canUseIntentionalDraw;
    arenaAnswerBoxEl.classList.toggle("hidden", !shouldShowBox);
    if (answerComposeEl) {
        answerComposeEl.classList.toggle("hidden", !canView);
    }
    arenaTurnEndBtnEl.classList.toggle("hidden", !canView);
    arenaAnswerInputEl.disabled = !canSubmit;
    arenaAnswerSubmitBtnEl.disabled = !canSubmit;
    arenaAnswerSubmitBtnEl.classList.toggle("hidden", !canView);
    arenaTurnEndBtnEl.disabled = !canEndTurn;
    if (arenaIntentionalDrawBtnEl) {
        arenaIntentionalDrawBtnEl.classList.toggle("hidden", !canUseIntentionalDraw);
        arenaIntentionalDrawBtnEl.disabled = !canUseIntentionalDraw;
    }
    arenaAnswerSubmitBtnEl.textContent = "アンサー";
    arenaAnswerSubmitBtnEl.setAttribute("aria-label", "アンサー");

    if (!canView) {
        arenaAnswerInputEl.value = "";
    }

    updateArenaAnswerLengthWarning();
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
    const hasRemainingActions = getCurrentTeamTotalActionPoints() > 0;
    const isFinalChance = isRightFinalActionBeforeTurnEnd();
    const finalChanceWarning = isRightFinalActionBeforeTurnEnd()
        ? "\n\nこのターンを終えると先攻の勝利となります。本当にターンエンドしますか？"
        : "";
    const warning = hasRemainingActions && !isFinalChance
        ? "\n\nアクション権が残っています。本当にターンエンドしますか？"
        : "";
    const confirmed = await showConfirmModal(
        isProposalMode
            ? `ターンエンドを提案しますか？${warning}${finalChanceWarning}`
            : `ターンエンドしますか？${warning}${finalChanceWarning}`,
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

async function submitIntentionalDrawProposal() {
    if (!canRequestIntentionalDraw()) return;

    if (intentionalDrawVoteRequestPending) {
        await showAlertModal("ID(インテンショナルドロー)提案処理中です。少し待ってください。");
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const confirmed = await showConfirmModal(
        "ID(インテンショナルドロー)は、ゲームが膠着状態になったときの救済措置として、全員の同意のもとこのゲームを引き分けにするルールです。\n\nIDを提案しますか？",
        {
            okLabel: "はい",
            cancelLabel: "いいえ",
        }
    );

    if (!confirmed) {
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    intentionalDrawVoteRequestPending = true;
    ws.send(
        JSON.stringify({
            type: "intentional_draw_vote_request",
            timestamp: Date.now(),
        })
    );

    window.setTimeout(() => {
        intentionalDrawVoteRequestPending = false;
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

    if (answerText.length > ANSWER_MAX_LENGTH) {
        await showAlertModal(`解答は${ANSWER_MAX_LENGTH}文字以内で入力してください`);
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
    updateArenaAnswerLengthWarning();
}

function updateChatLengthWarning(inputEl) {
    if (!inputEl) return;

    const warningEl = inputEl.closest(".chat-box")?.querySelector(".chat-length-warning");
    updateLengthWarning(inputEl, warningEl, CHAT_MAX_LENGTH);
}

function autoResizeChatInput(inputEl) {
    if (!inputEl || !inputEl.classList.contains("chat-input")) return;

    const computedStyle = window.getComputedStyle(inputEl);
    const maxHeight = parseFloat(computedStyle.maxHeight) || 140;

    inputEl.style.height = "auto";
    const nextHeight = Math.min(inputEl.scrollHeight, maxHeight);
    inputEl.style.height = `${nextHeight}px`;
    inputEl.style.overflowY = inputEl.scrollHeight > maxHeight ? "auto" : "hidden";
}

function updateLengthWarning(inputEl, warningEl, maxLength) {
    if (!inputEl || !warningEl) return;

    const reachedLimit = inputEl.value.length >= maxLength;
    warningEl.classList.toggle("hidden", !reachedLimit);
}

function updateQuestionLengthWarning() {
    if (!questionInputEl || !questionLengthCounterEl) return;

    const currentLength = countNormalizedQuestionChars(questionInputEl.value);
    questionLengthCounterEl.textContent = `${currentLength}/${QUESTION_MAX_LENGTH}`;

    if (questionLengthWarningEl) {
        questionLengthWarningEl.classList.toggle("hidden", currentLength < QUESTION_MAX_LENGTH);
    }
}

function updateArenaAnswerLengthWarning() {
    updateLengthWarning(arenaAnswerInputEl, arenaAnswerLengthWarningEl, ANSWER_MAX_LENGTH);
}

function canUseRoomCloseLabel(room) {
    const snapshot = room || currentRoomSnapshot;
    if (!snapshot || typeof snapshot !== "object") {
        return false;
    }
    const ownerId = String(snapshot.room_owner_id || "");
    const me = String(myClientId || "");
    return ownerId !== "" && me !== "" && ownerId === me && Boolean(snapshot.is_ai_mode);
}

function updateArenaLeaveLabel(modeOrRoom) {
    if (!leaveGameArenaEl) return;

    if (isKifuMode) {
        leaveGameArenaEl.textContent = "←一覧へ戻る";
        leaveGameArenaEl.setAttribute("aria-label", "一覧へ戻る");
        return;
    }

    const snapshot = (modeOrRoom && typeof modeOrRoom === "object") ? modeOrRoom : currentRoomSnapshot;
    const ownerId = String(snapshot?.room_owner_id || "");
    const me = String(myClientId || "");
    const isOwner = ownerId !== "" && me !== "" && ownerId === me;
    const isAiRoom = Boolean(snapshot?.is_ai_mode);

    // AI部屋は右上の閉じるボタンで管理し、退室リンクは通常表記にする。
    if (isOwner && !isAiRoom) {
        leaveGameArenaEl.textContent = "✕ 部屋を閉じる";
        leaveGameArenaEl.setAttribute("aria-label", "部屋を閉じる");
        return;
    }

    leaveGameArenaEl.textContent = "←退室する";
    leaveGameArenaEl.setAttribute("aria-label", "退室する");
}

function getTeamLabel(team) {
    return team === "team-right" ? "後攻" : "先攻";
}

function getPendingDisconnectAnnouncementText() {
    const pendingDisconnects = Array.isArray(currentRoomSnapshot?.pending_disconnects)
        ? currentRoomSnapshot.pending_disconnects
        : [];
    if (pendingDisconnects.length === 0) {
        return "";
    }

    const nowSeconds = Date.now() / 1000;
    const lines = [];
    pendingDisconnects.forEach((entry) => {
        const team = String(entry?.team || "");
        if (team !== "team-left" && team !== "team-right") {
            return;
        }

        const expiresAt = Number(entry?.expires_at || 0);
        if (!Number.isFinite(expiresAt) || expiresAt <= nowSeconds) {
            return;
        }

        const remainingSeconds = Math.max(0, Math.ceil(expiresAt - nowSeconds));
        const nickname = String(entry?.nickname || "ゲスト");
        const teamLabel = getTeamLabel(team);
        lines.push(`${teamLabel}: ${nickname} が接続タイムアウト中...（残り${remainingSeconds}秒）`);
    });

    return lines.join("\n");
}

function getArenaProgressAnnouncementText() {
    const roomState = currentRoomGameState || "waiting";
    const timeoutNotice = getPendingDisconnectAnnouncementText();

    let baseText = "";

    if (roomState === "finished" || currentGameState?.game_status === "finished") {
        const winner = String(currentGameState?.winner || "");
        if (winner === "team-left") {
            baseText = "対戦結果：先攻の勝利";
        } else if (winner === "team-right") {
            baseText = "対戦結果：後攻の勝利";
        } else {
            baseText = "対戦結果：引き分け";
        }
    } else if (roomState !== "playing") {
        const waitingOwnerLabel = currentRoomSnapshot?.is_ai_mode ? "作成者" : "出題者";
        baseText = `${waitingOwnerLabel}による開始を待っています...`;
    } else {
        const currentTurnLabel = getTeamLabel(currentGameState?.current_turn_team);
        if (currentGameState?.is_judging_answer) {
            baseText = `${currentTurnLabel}の解答の正誤判定中です...`;
        } else {
            baseText = `${currentTurnLabel}のターンです`;
        }
    }

    if (!timeoutNotice) {
        return baseText;
    }
    return `${baseText}\n${timeoutNotice}`;
}

function updateArenaProgressAnnouncement() {
    const announcementEl = document.getElementById("arena-progress-announcement");
    if (!announcementEl) return;

    announcementEl.textContent = getArenaProgressAnnouncementText();
}

function updateArenaReplayResultBadges({ show, winner }) {
    const leftBadgeEl = document.getElementById("arena-result-badge-left");
    const rightBadgeEl = document.getElementById("arena-result-badge-right");
    const badgeElements = [leftBadgeEl, rightBadgeEl].filter(Boolean);

    badgeElements.forEach((badgeEl) => {
        badgeEl.classList.add("hidden");
        badgeEl.classList.remove("is-win", "is-lose", "is-draw");
        badgeEl.textContent = "";
    });

    if (!show || badgeElements.length === 0) {
        return;
    }

    const winnerKey = String(winner || "").trim();
    if (winnerKey === "team-left") {
        if (leftBadgeEl) {
            leftBadgeEl.textContent = "勝利";
            leftBadgeEl.classList.add("is-win");
            leftBadgeEl.classList.remove("hidden");
        }
        if (rightBadgeEl) {
            rightBadgeEl.textContent = "敗北";
            rightBadgeEl.classList.add("is-lose");
            rightBadgeEl.classList.remove("hidden");
        }
        return;
    }

    if (winnerKey === "team-right") {
        if (leftBadgeEl) {
            leftBadgeEl.textContent = "敗北";
            leftBadgeEl.classList.add("is-lose");
            leftBadgeEl.classList.remove("hidden");
        }
        if (rightBadgeEl) {
            rightBadgeEl.textContent = "勝利";
            rightBadgeEl.classList.add("is-win");
            rightBadgeEl.classList.remove("hidden");
        }
        return;
    }

    if (winnerKey === "draw") {
        if (leftBadgeEl) {
            leftBadgeEl.textContent = "引き分け";
            leftBadgeEl.classList.add("is-draw");
            leftBadgeEl.classList.remove("hidden");
        }
        if (rightBadgeEl) {
            rightBadgeEl.textContent = "引き分け";
            rightBadgeEl.classList.add("is-draw");
            rightBadgeEl.classList.remove("hidden");
        }
    }
}

function updateGameStateUI() {
    // waiting -> playing へ遷移したタイミングで、出題前の選択状態を確実に破棄する
    if (previousRoomGameState !== "playing" && currentRoomGameState === "playing") {
        selectedArenaQuestionCharIndexes.clear();
        lastAutoSelectedQuestionKey = null;

        ["game-chat-log-team-left", "game-chat-log-team-right"].forEach((logId) => {
            const logEl = document.getElementById(logId);
            if (!logEl) return;
            const filterState = getChatLogFilterState(logEl);
            filterState.showChat = true;
            filterState.showLog = false;
        });
        refreshChatLogFilterControls();
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

        const shouldShowReplayResultBadges = isReplayMode() && !kifuReplayControlsEl?.classList.contains("hidden");
        updateArenaReplayResultBadges({
            show: shouldShowReplayResultBadges,
            winner: currentGameState?.winner,
        });

        updateArenaProgressAnnouncement();
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

    updateArenaReplayResultBadges({ show: false, winner: null });

    updateArenaProgressAnnouncement();
}

function showWaitingRoomScreen() {
    if (kifuListScreenEl) kifuListScreenEl.style.display = "none";
    document.getElementById("waiting-room-screen").style.display = "block";
    document.getElementById("game-arena-screen").style.display = "none";
    clearReplayState();
    document.body.dataset.appMode = isKifuMode ? "kifu" : "live";
    updateStartGameButtonVisibility(null);
    updateQuestionVisibilityButton();
    updateArenaAnswerFormVisibility();
    updateArenaCloseButtonVisibility(null);
    updateChatBoxVisibility();
    updateAiQuestionButtonState(currentRoomsSnapshot);
}

function showGameArenaScreen() {
    const wasInGameArena = isInGameArena();
    if (kifuListScreenEl) kifuListScreenEl.style.display = "none";
    document.getElementById("waiting-room-screen").style.display = "none";
    document.getElementById("game-arena-screen").style.display = "block";

    // 出題者は部屋に入った直後のみ、全開示表示を初期状態にする。
    if (!wasInGameArena && userRole === "questioner") {
        questionerViewMode = "all";
    }

    syncReplayControlsVisibility();
    document.body.dataset.appMode = isKifuMode ? "kifu" : "live";

    updateQuestionVisibilityButton();
    updateArenaAnswerFormVisibility();
    updateArenaCloseButtonVisibility(currentRoomSnapshot);
    updateChatBoxVisibility();
    updateAiQuestionButtonState(currentRoomsSnapshot);

    syncArenaLogsPresentation();
}

function showKifuListScreen() {
    document.getElementById("waiting-room-screen").style.display = "none";
    document.getElementById("game-arena-screen").style.display = "none";
    if (kifuListScreenEl) kifuListScreenEl.style.display = "block";
    clearReplayState();
    document.body.dataset.appMode = "live";
}

function isReplayMode() {
    return isKifuMode || isArenaReplayMode;
}

function syncReplayControlsVisibility() {
    if (kifuReplayControlsEl) {
        kifuReplayControlsEl.classList.toggle("hidden", !isReplayMode());
    }
}

function clearReplayState() {
    arenaReplayLoadToken += 1;
    clearReplayCurrentLogHighlights();
    isKifuMode = false;
    isArenaReplayMode = false;
    arenaReplayPendingRequestKey = "";
    currentArenaReplayRoomId = null;
    currentKifuDetail = null;
    currentKifuSteps = [];
    currentKifuStepIndex = 0;
    syncReplayControlsVisibility();
}

async function startFinishedArenaReplay(roomSnapshot) {
    if (isKifuMode) {
        return;
    }

    const roomId = String(roomSnapshot?.room_owner_id || "").trim();
    const kifuId = String(roomSnapshot?.kifu_id || "").trim();
    if (roomId === "" || kifuId === "") {
        return;
    }

    const replayRequestKey = `${roomId}:${kifuId}`;
    if (arenaReplayPendingRequestKey === replayRequestKey) {
        diagLog("arena_replay_skip_inflight", { room_id: roomId, kifu_id: kifuId });
        return;
    }

    if (isArenaReplayMode && currentArenaReplayRoomId === roomId && currentKifuDetail?.kifu_id === kifuId) {
        return;
    }

    const loadToken = ++arenaReplayLoadToken;
    currentArenaReplayRoomId = roomId;
    arenaReplayPendingRequestKey = replayRequestKey;

    try {
        const detail = await fetchKifuDetail(kifuId);
        if (loadToken !== arenaReplayLoadToken || isKifuMode) {
            return;
        }

        isArenaReplayMode = true;
        currentKifuDetail = detail;
        currentKifuSteps = buildKifuReplaySteps(detail);
        currentKifuStepIndex = Math.max(0, currentKifuSteps.length - 1);
        questionerViewMode = "all";
        syncReplayControlsVisibility();
        showGameArenaScreen();
        renderKifuStep();
    } catch {
        if (loadToken === arenaReplayLoadToken && !isKifuMode) {
            isArenaReplayMode = false;
            currentArenaReplayRoomId = null;
            syncReplayControlsVisibility();
        }
    } finally {
        if (arenaReplayPendingRequestKey === replayRequestKey) {
            arenaReplayPendingRequestKey = "";
        }
    }
}

function clearReplayCurrentLogHighlights() {
    ["game-chat-log-game-global", "game-chat-log-team-left", "game-chat-log-team-right"].forEach((logId) => {
        const logEl = document.getElementById(logId);
        if (!logEl) return;
        logEl.querySelectorAll(".event-log-item.kifu-log-current").forEach((itemEl) => {
            itemEl.classList.remove("kifu-log-current");
        });
    });
}

function highlightReplayCurrentLogFromDisplayedProgress() {
    clearReplayCurrentLogHighlights();

    const targetActionIndex = currentKifuStepIndex - 1;
    if (targetActionIndex < 0) {
        return;
    }

    const step = Array.isArray(currentKifuSteps) ? currentKifuSteps[currentKifuStepIndex] : null;
    const action = step?.action || null;
    const payload = (action && typeof action.payload === "object" && action.payload) ? action.payload : {};
    const actionType = String(action?.action_type || "").trim();
    const actionTimestamp = Number(action?.timestamp || 0);
    const replayEventTypesByAction = {
        open: ["character_opened"],
        answer: ["answer_result", "answer_attempt"],
        turn_end: ["turn_changed"],
        intentional_draw: ["intentional_draw"],
    };
    const targetEventTypes = replayEventTypesByAction[actionType] || [];

    const globalLogEl = document.getElementById("game-chat-log-game-global");
    if (!globalLogEl) {
        return;
    }

    const progressItems = Array.from(globalLogEl.querySelectorAll(".event-log-item:not(.filtered-out)")).filter((itemEl) => {
        const eventType = String(itemEl?.dataset?.eventType || "").trim();
        return REPLAY_PROGRESS_EVENT_TYPES.has(eventType);
    });

    if (progressItems.length === 0) {
        return;
    }

    let targetItem = null;
    if (targetEventTypes.length > 0) {
        const typedItems = progressItems.filter((itemEl) => targetEventTypes.includes(String(itemEl?.dataset?.eventType || "").trim()));
        if (typedItems.length > 0) {
            const getItemMessageText = (itemEl) => String(itemEl?.querySelector?.(".event-log-message")?.textContent || itemEl?.textContent || "").trim();

            if (actionType === "open") {
                const charIndex = Number(payload?.char_index);
                if (Number.isFinite(charIndex) && charIndex >= 0) {
                    const charLabel = `${charIndex + 1}文字目`;
                    const matchedByCharIndex = typedItems.filter((itemEl) => getItemMessageText(itemEl).includes(charLabel));
                    if (matchedByCharIndex.length > 0) {
                        targetItem = matchedByCharIndex[matchedByCharIndex.length - 1];
                    }
                }
            }

            if (!targetItem && actionType === "answer") {
                const answerText = String(payload?.answer_text || "").trim();
                const team = String(action?.team || "").trim();
                const teamLabel = team === "team-left" ? "先攻" : team === "team-right" ? "後攻" : "";

                if (answerText !== "") {
                    const answerNeedle = `「${answerText}」`;
                    const matchedByAnswerText = typedItems.filter((itemEl) => {
                        const message = getItemMessageText(itemEl);
                        if (!message.includes(answerNeedle)) {
                            return false;
                        }
                        if (teamLabel === "") {
                            return true;
                        }
                        return message.includes(`${teamLabel}が`);
                    });
                    if (matchedByAnswerText.length > 0) {
                        targetItem = matchedByAnswerText[matchedByAnswerText.length - 1];
                    }
                }
            }

            if (Number.isFinite(actionTimestamp) && actionTimestamp > 0) {
                const matchedByTime = typedItems.filter((itemEl) => {
                    const ts = Number(itemEl?.dataset?.eventTimestamp || 0);
                    return Number.isFinite(ts) && ts > 0 && ts <= actionTimestamp + 1000;
                });
                if (matchedByTime.length > 0) {
                    if (!targetItem) {
                        targetItem = matchedByTime[matchedByTime.length - 1];
                    }
                }
            }

            if (!targetItem) {
                const typedIndex = Math.max(0, Math.min(targetActionIndex, typedItems.length - 1));
                targetItem = typedItems[typedIndex];
            }
        }
    }

    if (!targetItem) {
        // ログが欠落していても、同手以前で最も近い進行ログを強調する。
        const safeIndex = Math.max(0, Math.min(targetActionIndex, progressItems.length - 1));
        targetItem = progressItems[safeIndex];
    }

    if (!targetItem) {
        return;
    }

    targetItem.classList.add("kifu-log-current");

    const scrollContainer = resolveLogScrollContainer(globalLogEl);
    if (!scrollContainer) {
        return;
    }

    const itemTop = targetItem.offsetTop;
    const itemBottom = itemTop + targetItem.offsetHeight;
    const viewTop = scrollContainer.scrollTop;
    const viewBottom = viewTop + scrollContainer.clientHeight;
    const margin = 24;
    const isOutsideView = itemTop < (viewTop + margin) || itemBottom > (viewBottom - margin);
    if (isOutsideView) {
        const nextTop = Math.max(0, itemTop - Math.max(0, (scrollContainer.clientHeight / 2) - (targetItem.offsetHeight / 2)));
        scrollContainer.scrollTop = nextTop;
    }
}

function getKifuApiClientId() {
    return String(myClientId || getOrCreatePersistentClientId() || "").trim();
}

function isNgrokHostname() {
    const host = String(window.location.hostname || "").toLowerCase();
    return host.endsWith(".ngrok-free.dev") || host.endsWith(".ngrok.app") || host === "ngrok.io";
}

function buildJsonApiFetchInit(baseInit = {}) {
    const headers = new Headers(baseInit.headers || {});
    if (!headers.has("Accept")) {
        headers.set("Accept", "application/json");
    }

    // ngrok free tier occasionally returns an HTML warning page for browser traffic.
    if (isNgrokHostname() && !headers.has("ngrok-skip-browser-warning")) {
        headers.set("ngrok-skip-browser-warning", "1");
    }

    return {
        ...baseInit,
        headers,
        cache: baseInit.cache || "no-store",
    };
}

async function fetchKifuList() {
    const clientId = getKifuApiClientId();
    diagLog("api_kifu_list_start", { client_id: clientId, ws: quizWsReadyStateLabel() });
    const response = await fetch(
        `/api/kifu/list?client_id=${encodeURIComponent(clientId)}`,
        buildJsonApiFetchInit()
    );
    diagLog("api_kifu_list_response", { status: response.status, ok: response.ok, client_id: clientId });
    if (!response.ok) {
        throw new Error("kifu_list_fetch_failed");
    }
    const data = await response.json();
    return Array.isArray(data?.kifu) ? data.kifu : [];
}

async function fetchKifuDetail(kifuId) {
    const clientId = getKifuApiClientId();
    diagLog("api_kifu_detail_start", { kifu_id: kifuId, client_id: clientId, ws: quizWsReadyStateLabel() });
    const response = await fetch(
        `/api/kifu/${encodeURIComponent(kifuId)}?client_id=${encodeURIComponent(clientId)}`,
        buildJsonApiFetchInit()
    );
    diagLog("api_kifu_detail_response", { status: response.status, ok: response.ok, kifu_id: kifuId, client_id: clientId });
    if (!response.ok) {
        throw new Error("kifu_detail_fetch_failed");
    }
    return response.json();
}

function renderKifuListRows(rows) {
    if (!kifuListEl) return;
    kifuListEl.innerHTML = "";

    if (!Array.isArray(rows) || rows.length === 0) {
        const emptyEl = document.createElement("div");
        emptyEl.className = "kifu-empty";
        emptyEl.textContent = "閲覧可能な棋譜はありません。";
        kifuListEl.appendChild(emptyEl);
        return;
    }

    rows.forEach((row) => {
        const cardEl = document.createElement("div");
        cardEl.className = "kifu-card";

        const titleEl = document.createElement("div");
        titleEl.className = "kifu-card-title";
        titleEl.textContent = `${row.questioner_name || "ゲスト"} の対戦`;

        const questionEl = document.createElement("div");
        questionEl.className = "kifu-card-question";
        const text = String(row.question_text || "");
        questionEl.textContent = text.length > 36 ? `${text.slice(0, 36)}...` : text;

        const metaEl = document.createElement("div");
        metaEl.className = "kifu-card-meta";
        const finishedAt = Number(row.finished_at || row.started_at || 0);
        const dateText = finishedAt > 0 ? new Date(finishedAt).toLocaleString() : "-";
        metaEl.textContent = `終了: ${dateText} / あなたの関与: ${getRoleDisplayLabel(row.your_role)}`;

        const openBtn = document.createElement("button");
        openBtn.type = "button";
        openBtn.className = "kifu-open-btn";
        openBtn.textContent = "棋譜を見る";
        openBtn.addEventListener("click", async () => {
            try {
                const detail = await fetchKifuDetail(row.kifu_id);
                enterKifuViewer(detail);
            } catch {
                void showAlertModal("棋譜の読み込みに失敗しました。");
            }
        });

        cardEl.appendChild(titleEl);
        cardEl.appendChild(questionEl);
        cardEl.appendChild(metaEl);
        cardEl.appendChild(openBtn);
        kifuListEl.appendChild(cardEl);
    });
}

function initializeReplayGameState() {
    return {
        current_turn_team: "team-left",
        game_status: "playing",
        winner: null,
        draw_reason: null,
        is_judging_answer: false,
        left_correct_waiting: false,
        team_left: {
            action_points: 1,
            bonus_action_points: 0,
            correct_answer: null,
        },
        team_right: {
            action_points: 0,
            bonus_action_points: 0,
            correct_answer: null,
        },
        opened_char_indexes: [],
        opened_by_team: {},
    };
}

function cloneReplayGameState(state) {
    return JSON.parse(JSON.stringify(state));
}

function replayTeamKey(team) {
    return team === "team-left" ? "team_left" : "team_right";
}

function replayOtherTeam(team) {
    return team === "team-left" ? "team-right" : "team-left";
}

function replayConsumeAction(teamState) {
    const action = Number(teamState.action_points || 0);
    const bonus = Number(teamState.bonus_action_points || 0);
    if (action > 0) {
        teamState.action_points = action - 1;
        return true;
    }
    if (bonus > 0) {
        teamState.bonus_action_points = bonus - 1;
        return true;
    }
    return false;
}

function replayYieldTurn(state) {
    const current = String(state.current_turn_team || "team-left");
    const currentKey = replayTeamKey(current);
    if (state[currentKey]) {
        state[currentKey].action_points = 0;
    }
    const nextTeam = current === "team-left" ? "team-right" : "team-left";
    state.current_turn_team = nextTeam;
    const nextKey = replayTeamKey(nextTeam);
    if (state[nextKey]) {
        state[nextKey].action_points = 1;
    }
}

function applyReplayAction(state, action) {
    const team = String(action?.team || "");
    const payload = typeof action?.payload === "object" && action?.payload ? action.payload : {};
    const teamKey = replayTeamKey(team);
    const otherTeamKey = replayTeamKey(replayOtherTeam(team));
    const teamState = state[teamKey] || { action_points: 0, bonus_action_points: 0, correct_answer: null };

    if (action?.action_type === "open") {
        const charIndex = Number(payload.char_index);
        const isYakumono = Boolean(payload.is_yakumono);
        if (Number.isFinite(charIndex)) {
            const openedSet = new Set(Array.isArray(state.opened_char_indexes) ? state.opened_char_indexes : []);
            openedSet.add(charIndex);
            state.opened_char_indexes = Array.from(openedSet).sort((a, b) => a - b);
            const owner = isYakumono ? "yakumono" : team;
            state.opened_by_team[String(charIndex)] = owner;
        }
        if (isYakumono) {
            teamState.action_points = Number(teamState.action_points || 0) + 1;
        }
        replayConsumeAction(teamState);
        const noAction = Number(teamState.action_points || 0) <= 0 && Number(teamState.bonus_action_points || 0) <= 0;
        if (noAction) {
            if (team === "team-right" && state.left_correct_waiting) {
                state.winner = "team-left";
                state.draw_reason = null;
                state.game_status = "finished";
                state.left_correct_waiting = false;
            } else {
                replayYieldTurn(state);
            }
        }
    }

    if (action?.action_type === "answer") {
        replayConsumeAction(teamState);
        const isCorrect = payload.is_correct;
        if (isCorrect === true) {
            teamState.correct_answer = true;
            if (team === "team-left") {
                state.left_correct_waiting = true;
                replayYieldTurn(state);
            } else if (state.left_correct_waiting) {
                state.winner = "draw";
                state.draw_reason = "double_correct";
                state.game_status = "finished";
                state.left_correct_waiting = false;
            } else {
                state.winner = "team-right";
                state.draw_reason = null;
                state.game_status = "finished";
            }
        } else if (isCorrect === false) {
            teamState.correct_answer = false;
            const otherState = state[otherTeamKey] || { action_points: 0, bonus_action_points: 0, correct_answer: null };
            otherState.bonus_action_points = Number(otherState.bonus_action_points || 0) + 1;
            state[otherTeamKey] = otherState;
            const noAction = Number(teamState.action_points || 0) <= 0 && Number(teamState.bonus_action_points || 0) <= 0;
            if (team === "team-right" && state.left_correct_waiting) {
                state.winner = "team-left";
                state.draw_reason = null;
                state.game_status = "finished";
                state.left_correct_waiting = false;
            } else if (noAction) {
                replayYieldTurn(state);
            }
        }
    }

    if (action?.action_type === "turn_end") {
        teamState.action_points = 0;
        if (team === "team-right" && state.left_correct_waiting) {
            state.winner = "team-left";
            state.draw_reason = null;
            state.game_status = "finished";
            state.left_correct_waiting = false;
        } else {
            replayYieldTurn(state);
        }
    }

    if (action?.action_type === "intentional_draw") {
        state.winner = "draw";
        state.draw_reason = "intentional_draw";
        state.game_status = "finished";
        state.left_correct_waiting = false;
        state.is_judging_answer = false;
    }

    state[teamKey] = teamState;
}

function buildKifuReplaySteps(detail) {
    const actions = Array.isArray(detail?.actions) ? detail.actions.filter((action) => {
        const actionType = String(action?.action_type || "");
        return actionType === "open" || actionType === "answer" || actionType === "turn_end" || actionType === "intentional_draw";
    }) : [];

    const steps = [];
    const state = initializeReplayGameState();
    steps.push({ game: cloneReplayGameState(state), action: null });

    actions.forEach((action) => {
        applyReplayAction(state, action);
        steps.push({
            game: cloneReplayGameState(state),
            action,
        });
    });
    return steps;
}

function buildReplayRoomSnapshot(detail, step) {
    const participants = detail?.participants_at_start || {};
    return {
        room_owner_id: detail?.room_owner_id,
        kifu_id: detail?.kifu_id,
        questioner_id: detail?.questioner?.client_id,
        questioner_name: detail?.questioner?.nickname || "ゲスト",
        question_text: String(detail?.question_text || ""),
        question_visible_text: String(detail?.question_text || ""),
        question_length: Number(detail?.question_length || 0),
        genre: String(detail?.genre || "").trim(),
        difficulty: Number.isFinite(Number(detail?.difficulty)) ? Number(detail?.difficulty) : 0,
        ai_model_id: String(detail?.ai_model_id || "").trim(),
        is_ai_mode: Boolean(detail?.is_ai_mode),
        yakumono_indexes: Array.isArray(detail?.yakumono_indexes) ? detail.yakumono_indexes : [],
        game_state: step?.game?.game_status === "finished" ? "finished" : "playing",
        game: step?.game || null,
        role: String(detail?.your_role || "questioner"),
        chat_role: "questioner",
        left_participants: Array.isArray(participants?.team_left) ? participants.team_left : [],
        right_participants: Array.isArray(participants?.team_right) ? participants.team_right : [],
        spectators: Array.isArray(detail?.spectators_ever) ? detail.spectators_ever : [],
        can_manage_room: String(detail?.room_owner_id || "") === String(myClientId || ""),
    };
}

function renderKifuStep() {
    if (!currentKifuDetail || !Array.isArray(currentKifuSteps) || currentKifuSteps.length === 0) {
        return;
    }
    currentKifuStepIndex = Math.max(0, Math.min(currentKifuStepIndex, currentKifuSteps.length - 1));
    const step = currentKifuSteps[currentKifuStepIndex];
    const roomSnapshot = buildReplayRoomSnapshot(currentKifuDetail, step);
    currentRoomSnapshot = roomSnapshot;
    currentRoomGameState = roomSnapshot.game_state;
    currentGameState = roomSnapshot.game;
    userRole = "questioner";
    updateArenaCloseButtonVisibility(roomSnapshot);
    document.body.dataset.chatRole = "questioner";
    document.body.dataset.roomRole = "owner";

    if (kifuStepLabelEl) {
        kifuStepLabelEl.textContent = `${currentKifuStepIndex} / ${Math.max(0, currentKifuSteps.length - 1)}`;
    }
    if (kifuStepPrevBtnEl) {
        kifuStepPrevBtnEl.disabled = currentKifuStepIndex <= 0;
    }
    if (kifuStepNextBtnEl) {
        kifuStepNextBtnEl.disabled = currentKifuStepIndex >= currentKifuSteps.length - 1;
    }
    if (kifuStepFirstBtnEl) {
        kifuStepFirstBtnEl.disabled = currentKifuStepIndex <= 0;
    }
    if (kifuStepLastBtnEl) {
        kifuStepLastBtnEl.disabled = currentKifuStepIndex >= currentKifuSteps.length - 1;
    }

    const shouldReplayLog = !isArenaReplayMode;
    const replayRoomId = shouldReplayLog ? `kifu:${currentKifuDetail.kifu_id}` : null;
    if (shouldReplayLog) {
        const state = getOrCreateArenaRoomLogState(replayRoomId);
        if (state) {
            state["team-left"] = [];
            state["team-right"] = [];
            state["game-global"] = [];
            const actions = currentKifuSteps.slice(1, currentKifuStepIndex + 1).map((it) => it.action).filter(Boolean);
            actions.forEach((action) => {
                const actionType = String(action.action_type || "");
                const team = String(action.team || "");
                const actorName = String(action.actor_name || "ゲスト");
                const subjectLabel = team === "team-left" ? "先攻" : team === "team-right" ? "後攻" : actorName;
                const payload = typeof action.payload === "object" && action.payload ? action.payload : {};
                if (actionType === "open") {
                    const index = Number(payload.char_index);
                    const label = Number.isFinite(index) ? `${index + 1}文字目` : "文字";
                    const message = `${subjectLabel}が${label}をオープンしました。`;
                    pushArenaRoomLog(replayRoomId, team || "game-global", "character_opened", message, action.timestamp || Date.now());
                    pushArenaRoomLog(replayRoomId, "game-global", "character_opened", message, action.timestamp || Date.now());
                } else if (actionType === "answer") {
                    const answerText = String(payload.answer_text || "");
                    const judgeText = payload.is_correct === true ? "正解" : payload.is_correct === false ? "誤答" : "判定待ち";
                    const message = `${subjectLabel}が「${answerText}」とアンサーしました（${judgeText}）。`;
                    pushArenaRoomLog(replayRoomId, team || "game-global", "answer_attempt", message, action.timestamp || Date.now());
                    pushArenaRoomLog(replayRoomId, "game-global", "answer_attempt", message, action.timestamp || Date.now());
                } else if (actionType === "turn_end") {
                    const message = `${subjectLabel}がターンエンドしました。`;
                    pushArenaRoomLog(replayRoomId, team || "game-global", "turn_changed", message, action.timestamp || Date.now());
                    pushArenaRoomLog(replayRoomId, "game-global", "turn_changed", message, action.timestamp || Date.now());
                } else if (actionType === "intentional_draw") {
                    const message = "IDが成立しました。";
                    pushArenaRoomLog(replayRoomId, "game-global", "intentional_draw", message, action.timestamp || Date.now());
                }
            });
        }
    }

    renderArena(roomSnapshot);
    updateGameStateUI();
    updateArenaAnswerFormVisibility();
    updateQuestionVisibilityButton();
    if (shouldReplayLog) {
        renderArenaLogsForRoom(replayRoomId, { forceScrollToBottom: true });
    }
    highlightReplayCurrentLogFromDisplayedProgress();
}

function enterKifuViewer(detail) {
    arenaReplayLoadToken += 1;
    isArenaReplayMode = false;
    currentArenaReplayRoomId = null;
    currentKifuDetail = detail;
    currentKifuSteps = buildKifuReplaySteps(detail);
    currentKifuStepIndex = 0;
    isKifuMode = true;
    questionerViewMode = "all";
    syncReplayControlsVisibility();
    showGameArenaScreen();
    if (closeRoomBtnEl) closeRoomBtnEl.classList.add("hidden");
    if (leaveGameArenaEl) {
        leaveGameArenaEl.textContent = "←一覧へ戻る";
        leaveGameArenaEl.setAttribute("aria-label", "一覧へ戻る");
    }
    renderKifuStep();
}

function exitKifuViewerToList() {
    clearReplayState();
    updateArenaLeaveLabel("guest");
    showKifuListScreen();
}

function isGameFinished() {
    return currentRoomGameState === "finished"
        || (currentRoomGameState === "playing" && currentGameState?.game_status === "finished");
}

function canToggleQuestionViewMode() {
    if (isKifuMode) {
        return isInGameArena();
    }

    if (!isInGameArena()) {
        return false;
    }

    if (userRole === "questioner") {
        return true;
    }

    if (isTeamLeftRevealWindow()) {
        return true;
    }

    const roomState = currentRoomGameState || "waiting";
    const isFinished = isGameFinished();

    // 対戦終了状態では参加者も切り替え可能
    if (isFinished && (userRole === "team-left" || userRole === "team-right")) {
        return true;
    }

    return userRole === "spectator" && (roomState === "playing" || roomState === "finished");
}

function getQuestionViewModeCycleForCurrentUser() {
    if (isKifuMode) {
        return QUESTIONER_VIEW_MODE_CYCLE;
    }

    if (userRole === "questioner") {
        return QUESTIONER_VIEW_MODE_CYCLE;
    }
    if (isTeamLeftRevealWindow()) {
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
    const canManageRoom = Boolean(currentRoom?.can_manage_room ?? currentRoomSnapshot?.can_manage_room);
    const canSee = isInGameArena() && roomState === "waiting" && (userRole === "questioner" || canManageRoom);
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

function updateArenaCloseButtonVisibility(currentRoom) {
    if (!closeRoomBtnEl) return;

    if (isKifuMode) {
        closeRoomBtnEl.classList.add("hidden");
        closeRoomBtnEl.style.display = "none";
        return;
    }

    const room = currentRoom || currentRoomSnapshot;
    const canShow = isInGameArena() && canUseRoomCloseLabel(room);
    closeRoomBtnEl.classList.toggle("hidden", !canShow);
    closeRoomBtnEl.style.display = canShow ? "" : "none";
}

async function requestCloseRoom(roomOwnerId) {
    const targetRoomOwnerId = String(roomOwnerId || "").trim();
    if (targetRoomOwnerId === "") {
        await showAlertModal("閉じる対象の部屋が見つかりません。");
        return;
    }

    const confirmed = await showConfirmModal(
        "この部屋を閉じますか？\n\n参加者と観戦者は全員ロビーへ戻ります。",
        {
            okLabel: "閉じる",
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

    ws.send(
        JSON.stringify({
            type: "cancel_question",
            room_owner_id: targetRoomOwnerId,
            timestamp: Date.now(),
        })
    );
}

function closeAllModals() {
    setArenaCharClickGuard();
    alertMessageEl.classList.remove("alert-winner-left", "alert-winner-right");
    if (alertModal.open) alertModal.close();
    if (confirmModal.open) confirmModal.close();
    if (aiQuestionModalEl && aiQuestionModalEl.open) aiQuestionModalEl.close();
    if (rulebookModalEl && rulebookModalEl.open) rulebookModalEl.close();
    const judgementModal = document.getElementById("answer-judgement-modal");
    if (judgementModal && !judgementModal.classList.contains("hidden")) {
        judgementModal.classList.add("hidden");
    }
    updateArenaInteractionLock();
}

function getWinnerAlertClass(message) {
    const text = String(message || "");
    if (text.includes("先攻の勝利")) {
        return "alert-winner-left";
    }
    if (text.includes("後攻の勝利")) {
        return "alert-winner-right";
    }
    return "";
}

function showAlertModal(message) {
    return new Promise((resolve) => {
        alertMessageEl.textContent = message;
        alertMessageEl.classList.remove("alert-winner-left", "alert-winner-right");
        const winnerAlertClass = getWinnerAlertClass(message);
        if (winnerAlertClass) {
            alertMessageEl.classList.add(winnerAlertClass);
        }
        if (!alertModal.open) {
            alertModal.showModal();
        }
        alertOkBtn.focus();
        setArenaCharClickGuard();
        updateArenaInteractionLock();

        const close = () => {
            setArenaCharClickGuard();
            if (alertModal.open) {
                alertModal.close();
            }
            alertMessageEl.classList.remove("alert-winner-left", "alert-winner-right");
            alertOkBtn.removeEventListener("click", onOk);
            alertModal.removeEventListener("click", onBackdropClick);
            alertModal.removeEventListener("cancel", onCancel);
            updateArenaInteractionLock();
            resolve();
        };

        const onOk = () => close();
        const onBackdropClick = (event) => {
            if (event.target === alertModal) {
                close();
            }
        };
        const onCancel = (event) => {
            event.preventDefault();
            close();
        };

        alertOkBtn.addEventListener("click", onOk, { once: true });
        alertModal.addEventListener("click", onBackdropClick);
        alertModal.addEventListener("cancel", onCancel);
    });
}

function buildGameFinishedAlertMessage(data) {
    const eventMessage = String(data?.event_message || "").trim();
    if (eventMessage !== "") {
        return eventMessage;
    }

    const winner = String(data?.current_room?.game?.winner || data?.event_payload?.winner || "").trim();
    if (winner === "team-left") {
        return "ゲーム終了！先攻の勝利";
    }
    if (winner === "team-right") {
        return "ゲーム終了！後攻の勝利";
    }
    return "ゲーム終了！引き分け";
}

function showQuestionConfirmModal(questionText) {
    return new Promise((resolve) => {
        confirmMessageEl.textContent = `以下の問題文で出題しますか？\n\nQ. ${questionText}`;

        const cardEl = confirmMessageEl.closest(".modal-card");
        const genreWrapEl = document.createElement("div");
        genreWrapEl.className = "question-confirm-genre-wrap";
        const genreLabelEl = document.createElement("label");
        genreLabelEl.className = "question-confirm-genre-label";
        genreLabelEl.setAttribute("for", "question-confirm-genre-input");
        genreLabelEl.textContent = "ジャンル（任意）";
        const genreInputEl = document.createElement("input");
        genreInputEl.id = "question-confirm-genre-input";
        genreInputEl.className = "question-confirm-genre-input";
        genreInputEl.type = "text";
        genreInputEl.maxLength = 40;
        genreInputEl.placeholder = "例: 歴史、音楽、アニメ";
        genreWrapEl.appendChild(genreLabelEl);
        genreWrapEl.appendChild(genreInputEl);
        if (cardEl && confirmActionsEl) {
            cardEl.insertBefore(genreWrapEl, confirmActionsEl);
        }

        confirmOkBtn.textContent = "出題する";
        confirmCancelBtn.textContent = "キャンセル";
        confirmCancelBtn.style.display = "";
        confirmActionsEl.classList.remove("single");

        if (!confirmModal.open) {
            confirmModal.showModal();
        }
        genreInputEl.focus();
        setArenaCharClickGuard();
        updateArenaInteractionLock();

        const close = (result) => {
            setArenaCharClickGuard();
            if (confirmModal.open) {
                confirmModal.close();
            }
            genreWrapEl.remove();
            confirmOkBtn.textContent = "送信する";
            confirmCancelBtn.textContent = "キャンセル";
            confirmCancelBtn.style.display = "";
            confirmActionsEl.classList.remove("single");
            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancelClick);
            confirmModal.removeEventListener("click", onBackdropClick);
            confirmModal.removeEventListener("cancel", onCancel);
            genreInputEl.removeEventListener("keydown", onGenreKeydown);
            updateArenaInteractionLock();
            resolve(result);
        };

        const onOk = () => close({
            confirmed: true,
            genre: String(genreInputEl.value || "").trim().slice(0, 40),
        });
        const onCancelClick = () => close(false);
        const onBackdropClick = (event) => {
            if (event.target === confirmModal) {
                close(false);
            }
        };
        const onCancel = (event) => {
            event.preventDefault();
            close(false);
        };
        const onGenreKeydown = (event) => {
            if (event.key !== "Enter" || event.isComposing) return;
            event.preventDefault();
            onOk();
        };

        confirmOkBtn.addEventListener("click", onOk, { once: true });
        confirmCancelBtn.addEventListener("click", onCancelClick, { once: true });
        confirmModal.addEventListener("click", onBackdropClick);
        confirmModal.addEventListener("cancel", onCancel);
        genreInputEl.addEventListener("keydown", onGenreKeydown);
    });
}

function showConfirmModal(message, options = {}) {
    const {
        hideCancel = false,
        okLabel = "送信する",
        cancelLabel = "キャンセル",
        requireExplicitChoice = false,
    } = options;
    return new Promise((resolve) => {
        confirmMessageEl.textContent = message;
        confirmOkBtn.textContent = okLabel;
        confirmCancelBtn.textContent = cancelLabel;
        confirmCancelBtn.style.display = hideCancel ? "none" : "";
        confirmActionsEl.classList.toggle("single", hideCancel);
        if (!confirmModal.open) {
            confirmModal.showModal();
        }
        confirmOkBtn.focus();
        setArenaCharClickGuard();
        updateArenaInteractionLock();

        const close = (result) => {
            setArenaCharClickGuard();
            if (confirmModal.open) {
                confirmModal.close();
            }
            confirmCancelBtn.style.display = "";
            confirmActionsEl.classList.remove("single");
            confirmOkBtn.textContent = "送信する";
            confirmCancelBtn.textContent = "キャンセル";
            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancelClick);
            confirmModal.removeEventListener("click", onBackdropClick);
            confirmModal.removeEventListener("cancel", onCancel);
            updateArenaInteractionLock();
            resolve(result);
        };

        const onOk = () => close(true);
        const onCancelClick = () => close(false);
        const onBackdropClick = (event) => {
            if (event.target === confirmModal) {
                if (requireExplicitChoice) {
                    return;
                }
                close(hideCancel ? true : false);
            }
        };
        const onCancel = (event) => {
            event.preventDefault();
            if (requireExplicitChoice) {
                return;
            }
            close(hideCancel ? true : false);
        };

        confirmOkBtn.addEventListener("click", onOk, { once: true });
        confirmCancelBtn.addEventListener("click", onCancelClick, { once: true });
        confirmModal.addEventListener("click", onBackdropClick);
        confirmModal.addEventListener("cancel", onCancel);
    });
}

function setAiQuestionLoading(loading) {
    aiQuestionRequestPending = Boolean(loading);

    updateAiQuestionButtonState();

    if (aiQuestionSpinnerEl) {
        aiQuestionSpinnerEl.classList.toggle("hidden", !aiQuestionRequestPending);
    }

    if (aiQuestionModalSubmitBtnEl) {
        aiQuestionModalSubmitBtnEl.disabled = aiQuestionRequestPending;
    }

    if (aiQuestionModalCancelBtnEl) {
        aiQuestionModalCancelBtnEl.disabled = aiQuestionRequestPending;
    }

    if (aiModelSelectEl) {
        aiModelSelectEl.disabled = aiQuestionRequestPending;
    }

    if (aiAccuracyRateRangeEl) {
        aiAccuracyRateRangeEl.disabled = aiQuestionRequestPending;
    }

    if (questionInputEl) {
        questionInputEl.disabled = aiQuestionRequestPending;
    }
}

function showAiGenreInputModal() {
    return new Promise((resolve) => {
        if (!aiQuestionModalEl || !aiGenreInputEl || !aiModelSelectEl || !aiAccuracyRateRangeEl) {
            resolve(null);
            return;
        }

        void loadAiModelOptions().then((loaded) => {
            if (!loaded || aiModelOptions.length === 0) {
                void showAlertModal("AIモデル一覧の取得に失敗しました。時間をおいて再度お試しください。").then(() => close(null));
                return;
            }

            populateAiModelSelect();
            initializeAiAccuracyRateControl();
            aiGenreInputEl.value = "";
            aiModelSelectEl.value = defaultAiModelId;
            aiAccuracyRateRangeEl.value = String(DEFAULT_AI_ACCURACY_RATE);
            updateAiAccuracyRateDisplay(aiAccuracyRateRangeEl.value);
            setAiQuestionLoading(false);

            if (!aiQuestionModalEl.open) {
                aiQuestionModalEl.showModal();
            }
            aiGenreInputEl.focus();
            updateArenaInteractionLock();
        });

        const close = (value) => {
            if (aiQuestionModalEl.open) {
                aiQuestionModalEl.close();
            }
            aiQuestionModalSubmitBtnEl?.removeEventListener("click", onSubmit);
            aiQuestionModalCancelBtnEl?.removeEventListener("click", onCancelClick);
            aiQuestionModalEl.removeEventListener("click", onBackdropClick);
            aiQuestionModalEl.removeEventListener("cancel", onCancel);
            aiGenreInputEl.removeEventListener("keydown", onKeydown);
            aiAccuracyRateRangeEl.removeEventListener("input", onRateInput);
            updateArenaInteractionLock();
            resolve(value);
        };

        const onSubmit = () => {
            const genre = String(aiGenreInputEl.value || "").trim();
            const modelId = String(aiModelSelectEl.value || defaultAiModelId).trim() || defaultAiModelId;
            const accuracyRate = normalizeAiAccuracyRate(aiAccuracyRateRangeEl.value);
            close({ genre, modelId, accuracyRate });
        };
        const onCancelClick = () => close(null);
        const onBackdropClick = (event) => {
            if (event.target === aiQuestionModalEl) {
                close(null);
            }
        };
        const onCancel = (event) => {
            event.preventDefault();
            close(null);
        };
        const onKeydown = (event) => {
            if (event.key !== "Enter" || event.isComposing) return;
            event.preventDefault();
            onSubmit();
        };
        const onRateInput = () => updateAiAccuracyRateDisplay(aiAccuracyRateRangeEl.value);

        aiQuestionModalSubmitBtnEl?.addEventListener("click", onSubmit, { once: true });
        aiQuestionModalCancelBtnEl?.addEventListener("click", onCancelClick, { once: true });
        aiQuestionModalEl.addEventListener("click", onBackdropClick);
        aiQuestionModalEl.addEventListener("cancel", onCancel);
        aiGenreInputEl.addEventListener("keydown", onKeydown);
        aiAccuracyRateRangeEl.addEventListener("input", onRateInput);
    });
}

function renderParticipants(participants) {
    const listEl = document.getElementById("participants-list");
    listEl.innerHTML = "";

    if (!Array.isArray(participants) || participants.length === 0) {
        const emptyItem = document.createElement("li");
        emptyItem.className = "player-list-item player-list-item-empty";
        emptyItem.textContent = "参加者はいません";
        listEl.appendChild(emptyItem);
        return;
    }

    participants.forEach((participant) => {
        const item = document.createElement("li");
        item.className = "player-list-item";
        const nickname = participant.nickname || "ゲスト";
        const isMe = participant.client_id === myClientId;

        const nameEl = document.createElement("span");
        nameEl.className = "player-list-item-name";
        nameEl.textContent = nickname;
        item.appendChild(nameEl);

        if (isMe) {
            item.classList.add("player-list-item-me");
            const meTagEl = document.createElement("span");
            meTagEl.className = "player-list-item-tag";
            meTagEl.textContent = "You";
            item.appendChild(meTagEl);
        }

        listEl.appendChild(item);
    });
}

function canSwapParticipantsInWaitingRoom() {
    if (isKifuMode) {
        return false;
    }
    if (!isInGameArena()) {
        return false;
    }
    return (currentRoomGameState || "waiting") === "waiting"
        && Boolean(currentRoomSnapshot?.can_manage_room);
}

function requestSwapParticipantTeam(targetClientId) {
    const targetId = String(targetClientId || "").trim();
    if (targetId === "") {
        return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    ws.send(
        JSON.stringify({
            type: "swap_participant_team",
            target_client_id: targetId,
            timestamp: Date.now(),
        })
    );
}

function renderNameList(listEl, names, options = {}) {
    listEl.innerHTML = "";
    if (!Array.isArray(names) || names.length === 0) {
        const emptyItem = document.createElement("li");
        emptyItem.className = "player-list-item player-list-item-empty";
        emptyItem.textContent = "なし";
        listEl.appendChild(emptyItem);
        return;
    }

    const team = String(options?.team || "").trim();
    const allowSwap = Boolean(options?.allowSwap)
        && (team === "team-left" || team === "team-right");

    names.forEach((entry) => {
        const item = document.createElement("li");
        item.className = "player-list-item";
        if (typeof entry === "string") {
            const nameEl = document.createElement("span");
            nameEl.className = "player-list-item-name";
            nameEl.textContent = entry;
            item.appendChild(nameEl);
            listEl.appendChild(item);
            return;
        }

        const nickname = entry?.nickname || "ゲスト";
        const isMe = entry?.client_id === myClientId;

        const nameEl = document.createElement("span");
        nameEl.className = "player-list-item-name";
        nameEl.textContent = nickname;
        item.appendChild(nameEl);

        if (isMe) {
            item.classList.add("player-list-item-me");
            const meTagEl = document.createElement("span");
            meTagEl.className = "player-list-item-tag";
            meTagEl.textContent = "You";
            item.appendChild(meTagEl);
        }

        if (allowSwap && entry?.client_id) {
            const swapBtnEl = document.createElement("button");
            swapBtnEl.type = "button";
            swapBtnEl.className = "player-swap-btn";
            swapBtnEl.title = team === "team-left" ? "後攻へ移動" : "先攻へ移動";
            swapBtnEl.setAttribute("aria-label", `${nickname} を ${team === "team-left" ? "後攻" : "先攻"}に入れ替える`);

            const iconEl = document.createElement("img");
            iconEl.src = "img/swap.png";
            iconEl.alt = "";
            iconEl.className = "player-swap-icon";
            swapBtnEl.appendChild(iconEl);

            swapBtnEl.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                requestSwapParticipantTeam(entry.client_id);
            });

            item.insertBefore(swapBtnEl, item.firstChild);
        }

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

function countNormalizedQuestionChars(text) {
    const graphemes = splitIntoGraphemes(String(text || ""));
    return graphemes.filter((ch) => ch !== "\n" && ch !== "\r").length;
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

    if (questionerViewMode === "all" && isTeamLeftRevealWindow()) {
        return "questioner";
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
    const questionerListEl = document.getElementById("arena-questioner-list");
    const roomMetaEl = document.getElementById("arena-room-meta");
    const questionEl = document.getElementById("arena-question-text");
    const leftListEl = document.getElementById("arena-player-left-list");
    const rightListEl = document.getElementById("arena-player-right-list");
    const spectatorListEl = document.getElementById("arena-spectator-list");

    if (!currentRoom) {
        if (questionerListEl) {
            questionerListEl.innerHTML = "";
            const emptyItemEl = document.createElement("li");
            emptyItemEl.className = "player-list-item questioner-list-item player-list-item-empty";
            emptyItemEl.textContent = "出題者: -";
            questionerListEl.appendChild(emptyItemEl);
        } else if (titleEl) {
            titleEl.textContent = "出題者: -";
        }
        if (roomMetaEl) {
            roomMetaEl.innerHTML = "";
        }
        currentArenaQuestionRawText = "";
        questionerViewMode = "all";
        selectedArenaQuestionCharIndexes.clear();
        lastAutoSelectedQuestionKey = null;
        questionEl.textContent = "問題文を準備中...";
        updateQuestionVisibilityButton();
        renderNameList(leftListEl, [], { team: "team-left", allowSwap: false });
        renderNameList(rightListEl, [], { team: "team-right", allowSwap: false });
        renderNameList(spectatorListEl, [], { team: "spectator", allowSwap: false });
        updateArenaProgressAnnouncement();
        return;
    }

    const isMeQuestioner = currentRoom.questioner_id === myClientId;
    const questionerName = String(currentRoom.questioner_name || "ゲスト");
    const isIntentionalDrawReplay = isReplayMode()
        && !kifuReplayControlsEl?.classList.contains("hidden")
        && String(currentRoom?.game?.winner || "").trim() === "draw"
        && String(currentRoom?.game?.draw_reason || "").trim() === "intentional_draw";
    const genreLabel = String(currentRoom.genre || "").trim() || "未設定";
    const difficultyLabel = currentRoom.is_ai_mode
        ? `${normalizeAiAccuracyRate(currentRoom.difficulty)}%`
        : "未設定";
    const modelLabel = getAiModelDisplayText(currentRoom.ai_model_id);
    const shouldShowGenre = String(currentRoom.genre || "").trim() !== "";
    const shouldShowDifficulty = Boolean(currentRoom.is_ai_mode) && difficultyLabel !== "未設定";
    const shouldShowModel = Boolean(currentRoom.is_ai_mode) && modelLabel !== "未設定";
    if (questionerListEl) {
        questionerListEl.innerHTML = "";
        const questionerItemEl = document.createElement("li");
        questionerItemEl.className = "player-list-item questioner-list-item";

        const questionerNameEl = document.createElement("span");
        questionerNameEl.className = "player-list-item-name";
        questionerNameEl.textContent = `出題者: ${questionerName}`;
        questionerItemEl.appendChild(questionerNameEl);

        if (isIntentionalDrawReplay) {
            const loseTagEl = document.createElement("span");
            loseTagEl.className = "arena-result-badge questioner-result-badge is-lose";
            loseTagEl.textContent = "敗北";
            questionerItemEl.appendChild(loseTagEl);
        }

        if (isMeQuestioner && !currentRoom.is_ai_mode) {
            questionerItemEl.classList.add("player-list-item-me", "questioner-list-item-me");
            const meTagEl = document.createElement("span");
            meTagEl.className = "player-list-item-tag";
            meTagEl.textContent = "You";
            questionerItemEl.appendChild(meTagEl);
        }

        questionerListEl.appendChild(questionerItemEl);
    } else if (titleEl) {
        titleEl.textContent = `出題者: ${questionerName}${isMeQuestioner ? " (You)" : ""}`;
    }

    if (roomMetaEl) {
        roomMetaEl.innerHTML = "";

        if (shouldShowGenre) {
            const genreChipEl = document.createElement("span");
            genreChipEl.className = "arena-room-meta-chip";
            genreChipEl.textContent = `ジャンル: ${genreLabel}`;
            roomMetaEl.appendChild(genreChipEl);
        }

        if (shouldShowDifficulty) {
            const difficultyChipEl = document.createElement("span");
            difficultyChipEl.className = "arena-room-meta-chip";
            difficultyChipEl.textContent = `難易度: ${difficultyLabel}`;
            roomMetaEl.appendChild(difficultyChipEl);
        }

        if (shouldShowModel) {
            const modelChipEl = document.createElement("span");
            modelChipEl.className = "arena-room-meta-chip";
            modelChipEl.textContent = `モデル: ${modelLabel}`;
            roomMetaEl.appendChild(modelChipEl);
        }
    }

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

    const canSwap = canSwapParticipantsInWaitingRoom();
    renderNameList(leftListEl, leftPlayers, { team: "team-left", allowSwap: canSwap });
    renderNameList(rightListEl, rightPlayers, { team: "team-right", allowSwap: canSwap });
    renderNameList(spectatorListEl, currentRoom.spectators || [], { team: "spectator", allowSwap: false });
    updateArenaProgressAnnouncement();
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
        updateAiQuestionButtonState(rooms);
        return;
    }

    rooms.forEach((room) => {
        const card = document.createElement("div");
        card.className = "room-card";

        const questionerEl = document.createElement("div");
        questionerEl.className = "room-card-questioner";
        if (room.is_ai_room) {
            const ownerName = String(room.room_owner_name || "ゲスト");
            questionerEl.textContent = `AIの部屋(作成者:${ownerName})`;
        } else {
            questionerEl.textContent = `${room.questioner_name} の部屋`;
        }

        const metaEl = document.createElement("div");
        metaEl.className = "room-card-meta";
        const roomState = String(room.game_state || "waiting");
        const gameStateLabelByState = {
            waiting: "準備中",
            playing: "対戦中",
            finished: "対戦終了",
        };
        const gameStateLabel = gameStateLabelByState[roomState] || "準備中";
        const genreLabel = String(room.genre || "").trim() || "未設定";
        metaEl.textContent = `状態 ${gameStateLabel} / 参加 ${room.participant_count}人 / 観戦 ${room.spectator_count}人 / ジャンル:${genreLabel}`;

        const shouldShowJoinActions = !room.is_owner || Boolean(room.is_ai_room);
        if (shouldShowJoinActions) {
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

            const canShowClose = Boolean(room.is_owner) && Boolean(room.is_ai_room) && String(room.game_state || "") === "finished";
            if (canShowClose) {
                const closeBtn = document.createElement("button");
                closeBtn.type = "button";
                closeBtn.className = "room-card-btn danger";
                closeBtn.textContent = "閉じる";
                closeBtn.addEventListener("click", () => {
                    void requestCloseRoom(room.room_owner_id);
                });
                actionsEl.appendChild(closeBtn);
            }

            card.appendChild(actionsEl);
        }

        card.appendChild(questionerEl);
        card.appendChild(metaEl);
        roomListEl.appendChild(card);
    });

    updateAiQuestionButtonState(rooms);
}

function createEventLogItem(eventType, eventMessage, eventTimestamp = null, logMarkerId = null, eventId = null, eventRevision = 1, eventVersion = 0) {
    if (!eventMessage) {
        return null;
    }

    const item = document.createElement("div");
    item.className = "event-log-item";
    item.dataset.eventType = String(eventType || "");
    if (logMarkerId) {
        item.dataset.logMarkerId = String(logMarkerId);
    }
    if (eventId) {
        item.dataset.eventId = String(eventId);
    }
    item.dataset.eventRevision = String(Math.max(1, Number(eventRevision || 1)));
    item.dataset.eventVersion = String(Math.max(0, Number(eventVersion || 0)));
    const numericEventTimestamp = Number(eventTimestamp);
    const resolvedEventTimestamp = Number.isFinite(numericEventTimestamp) && numericEventTimestamp > 0
        ? Math.floor(numericEventTimestamp)
        : Date.now();
    item.dataset.eventTimestamp = String(resolvedEventTimestamp);

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
        item.classList.add("is-chat-event");
        const separatorMatch = eventMessage.match(/^([^:：]+[:：]\s*)([\s\S]*)$/);
        if (separatorMatch) {
            messageEl.classList.add("chat");
            buildSplitMessage("event-log-chat-name", "event-log-chat-body", separatorMatch);
        } else {
            messageEl.textContent = eventMessage;
        }
    } else if (
        eventType === "join"
        || eventType === "leave"
        || eventType === "question"
        || eventType === "room_entry"
        || eventType === "room_exit"
    ) {
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

    const normalizedMessage = String(eventMessage || "");
    const isGameFinishedLog = eventType === "game_finished"
        || normalizedMessage.includes("ゲーム終了")
        || normalizedMessage.includes("対戦結果：");
    if (isGameFinishedLog) {
        messageEl.classList.add("game-finished");
        if (normalizedMessage.includes("先攻の勝利") || normalizedMessage.includes("先攻勝ち")) {
            messageEl.classList.add("game-finished-left-win");
        } else if (normalizedMessage.includes("後攻の勝利") || normalizedMessage.includes("後攻勝ち")) {
            messageEl.classList.add("game-finished-right-win");
        } else if (normalizedMessage.includes("引き分け") || normalizedMessage.includes("ドロー")) {
            messageEl.classList.add("game-finished-draw");
        }
    }

    const timestampEl = document.createElement("span");
    timestampEl.className = "event-log-time";
    const timestampDate = new Date(resolvedEventTimestamp);
    timestampEl.textContent = timestampDate.toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });

    item.appendChild(messageEl);
    item.appendChild(timestampEl);
    return item;
}

function insertLogItemByOrder(logEl, itemEl) {
    if (!logEl || !itemEl) {
        return;
    }

    let cursor = logEl.lastElementChild;
    while (cursor) {
        const order = compareArenaLogOrder(
            Number(cursor.dataset?.eventTimestamp || 0),
            Number(cursor.dataset?.eventVersion || 0),
            Number(itemEl.dataset?.eventTimestamp || 0),
            Number(itemEl.dataset?.eventVersion || 0),
        );
        if (order <= 0) {
            break;
        }
        cursor = cursor.previousElementSibling;
    }

    if (cursor) {
        logEl.insertBefore(itemEl, cursor.nextElementSibling);
    } else {
        logEl.insertBefore(itemEl, logEl.firstChild);
    }
}

function appendLogToContainer(
    logEl,
    eventType,
    eventMessage,
    eventTimestamp = null,
    logMarkerId = null,
    eventId = null,
    eventRevision = 1,
    eventVersion = 0,
) {
    if (!logEl) {
        return;
    }

    const scrollContainer = resolveLogScrollContainer(logEl);
    const wasNearBottom = isLogNearBottom(scrollContainer);
    const indicatorEl = ensureLogNewIndicator(scrollContainer);

    if (eventId) {
        const existingItem = logEl.querySelector(`[data-event-id="${CSS.escape(String(eventId))}"]`);
        if (existingItem) {
            const existingRevision = Math.max(1, Number(existingItem.dataset.eventRevision || 1));
            const nextRevision = Math.max(1, Number(eventRevision || 1));
            if (nextRevision < existingRevision) {
                return;
            }

            const replacementTimestamp = resolveReplacementEventTimestamp(existingItem.dataset.eventTimestamp, eventTimestamp);
            const newItem = createEventLogItem(eventType, eventMessage, replacementTimestamp, logMarkerId, eventId, nextRevision, eventVersion);
            if (newItem) {
                existingItem.remove();
                insertLogItemByOrder(logEl, newItem);
                if (logEl.classList.contains("chat-log")) {
                    applyChatLogFilterToItem(newItem, getChatLogFilterState(logEl));
                }
            }
            return;
        }
    }

    // If logMarkerId is provided and there's an existing log with the same marker, replace it
    if (logMarkerId) {
        const existingItem = logEl.querySelector(`[data-log-marker-id="${CSS.escape(String(logMarkerId))}"]`);
        if (existingItem) {
            const replacementTimestamp = resolveReplacementEventTimestamp(existingItem.dataset.eventTimestamp, eventTimestamp);
            const newItem = createEventLogItem(eventType, eventMessage, replacementTimestamp, logMarkerId, eventId, eventRevision, eventVersion);
            if (newItem) {
                existingItem.remove();
                insertLogItemByOrder(logEl, newItem);
                if (logEl.classList.contains("chat-log")) {
                    applyChatLogFilterToItem(newItem, getChatLogFilterState(logEl));
                }
            }
            return;
        }
    }

    const item = createEventLogItem(eventType, eventMessage, eventTimestamp, logMarkerId, eventId, eventRevision, eventVersion);
    if (!item) {
        return;
    }

    insertLogItemByOrder(logEl, item);
    if (logEl.classList.contains("chat-log")) {
        applyChatLogFilterToItem(item, getChatLogFilterState(logEl));
    }
    while (logEl.children.length > 50) {
        logEl.removeChild(logEl.firstChild);
    }

    if (!scrollContainer) {
        return;
    }

    if (wasNearBottom) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
        if (indicatorEl) {
            indicatorEl.classList.add("hidden");
        }
        return;
    }

    if (indicatorEl) {
        indicatorEl.classList.remove("hidden");
    }
}

function appendEventLog(
    eventType,
    eventMessage,
    eventChatType = null,
    eventRoomId = null,
    eventTimestamp = null,
    logMarkerId = null,
    eventId = null,
    eventRevision = 1,
    eventVersion = 0,
) {
    const record = normalizeArenaEventRecord({
        event_type: eventType,
        event_chat_type: eventChatType,
        event_message: eventMessage,
        event_room_id: eventRoomId,
        timestamp: eventTimestamp,
        event_id: eventId,
        event_revision: eventRevision,
        event_version: eventVersion,
        log_marker_id: logMarkerId,
    });

    if (!ARENA_ALLOWED_EVENT_TYPES.has(record.eventType) || !record.eventMessage) {
        return;
    }

    if (HIDDEN_ARENA_EVENT_TYPES.has(record.eventType)) {
        return;
    }

    const displayMessage = getArenaDisplayedMessageForViewer(record);

    // チャット種別が指定されているイベントは、対応するゲーム内ログに流す。
    if (record.eventChatType && record.eventChatType !== "lobby") {
        const resolvedRoomId = record.roomId;
        const shouldMirrorToGlobal = shouldMirrorArenaEventToGlobal(record);
        if (resolvedRoomId !== "") {
            pushArenaRoomLog(
                resolvedRoomId,
                record.eventChatType,
                record.eventType,
                record.eventMessage,
                record.eventTimestamp,
                record.logMarkerId,
                record.eventId,
                record.eventRevision,
                record.eventVersion,
            );
            if (shouldDuplicateOpenResolvedToBothTeamLogs(record)) {
                const oppositeChatType = record.eventChatType === "team-left" ? "team-right" : "team-left";
                pushArenaRoomLog(
                    resolvedRoomId,
                    oppositeChatType,
                    record.eventType,
                    record.eventMessage,
                    record.eventTimestamp,
                    record.logMarkerId,
                    record.eventId,
                    record.eventRevision,
                    record.eventVersion,
                );
            }
            if (shouldMirrorToGlobal) {
                pushArenaRoomLog(
                    resolvedRoomId,
                    "game-global",
                    record.eventType,
                    displayMessage,
                    record.eventTimestamp,
                    record.logMarkerId,
                    record.eventId,
                    record.eventRevision,
                    record.eventVersion,
                );
            }
        }

        if (resolvedRoomId !== "" && currentArenaLogRoomId !== resolvedRoomId) {
            debugArenaHistory("appendEventLog skipped due to room mismatch", {
                eventType: record.eventType,
                eventChatType: record.eventChatType,
                resolvedRoomId,
                currentArenaLogRoomId,
            });
            return;
        }

        const roomLogEl = document.getElementById(`game-chat-log-${record.eventChatType}`);
        appendLogToContainer(roomLogEl, record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
        if (shouldDuplicateOpenResolvedToBothTeamLogs(record)) {
            const oppositeChatType = record.eventChatType === "team-left" ? "team-right" : "team-left";
            const oppositeLogEl = document.getElementById(`game-chat-log-${oppositeChatType}`);
            appendLogToContainer(oppositeLogEl, record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
        }
        if (shouldMirrorToGlobal) {
            const globalLogEl = document.getElementById("game-chat-log-game-global");
            appendLogToContainer(globalLogEl, record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
        }
        return;
    }

    // アリーナ滞在中は部屋の入退室ログを全体チャットログにも表示する。
    if ((record.eventType === "room_entry" || record.eventType === "room_exit") && isInGameArena()) {
        const resolvedRoomId = record.roomId;
        if (resolvedRoomId !== "") {
            pushArenaRoomLog(resolvedRoomId, "game-global", record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
        }

        if (resolvedRoomId === "" || currentArenaLogRoomId === null || currentArenaLogRoomId === resolvedRoomId) {
            const globalLogEl = document.getElementById("game-chat-log-game-global");
            appendLogToContainer(globalLogEl, record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
        }
        return;
    }

    if (record.eventType === "room_entry" || record.eventType === "room_exit") {
        return;
    }

    // アリーナ内で発生するゲーム進行ログは待機所ログへは送らない。
    const arenaOnlyTypes = new Set([
        "game_start",
        "game_finished",
        "question",
        "room_shuffle",
        "character_opened",
        "answer_submitted",
        "open_vote_request",
        "open_vote_resolved",
        "answer_attempt",
        "answer_result",
        "answer_vote_request",
        "answer_vote_resolved",
        "turn_end_vote_request",
        "turn_end_vote_resolved",
        "intentional_draw_vote_request",
        "intentional_draw_vote_resolved",
        "intentional_draw",
        "turn_changed",
    ]);
    if (arenaOnlyTypes.has(record.eventType)) {
        const resolvedRoomId = record.roomId;
        if (isInGameArena() && resolvedRoomId !== "") {
            pushArenaRoomLog(resolvedRoomId, "game-global", record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
            if (currentArenaLogRoomId === null || currentArenaLogRoomId === resolvedRoomId) {
                const globalLogEl = document.getElementById("game-chat-log-game-global");
                appendLogToContainer(globalLogEl, record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
            }
        }
        return;
    }

    const waitingLogEl = document.getElementById("event-log");
    appendLogToContainer(waitingLogEl, record.eventType, displayMessage, record.eventTimestamp, record.logMarkerId, record.eventId, record.eventRevision, record.eventVersion);
}

function hydrateLobbyChatHistoryIfNeeded(history) {
    if (!Array.isArray(history)) {
        return;
    }

    const sortedHistory = [...history]
        .filter((entry) => entry && typeof entry === "object")
        .sort((a, b) => {
            const timeDiff = Number(a?.timestamp || 0) - Number(b?.timestamp || 0);
            if (timeDiff !== 0) return timeDiff;
            return Number(a?.seq || 0) - Number(b?.seq || 0);
        });

    const historySignature = sortedHistory.length > 0
        ? `${sortedHistory.length}:${Number(sortedHistory[sortedHistory.length - 1]?.seq || 0)}:${String(sortedHistory[sortedHistory.length - 1]?.event_id || "")}`
        : "0";
    if (historySignature === lastLobbyHistorySignature) {
        return;
    }
    lastLobbyHistorySignature = historySignature;

    const waitingLogEl = document.getElementById("event-log");
    if (!waitingLogEl) {
        return;
    }

    waitingLogEl.innerHTML = "";
    sortedHistory.forEach((entry) => {
        const eventType = String(entry?.event_type || "").trim();
        const eventMessage = String(entry?.event_message || "").trim();
        if (!ARENA_ALLOWED_EVENT_TYPES.has(eventType) || eventMessage === "") {
            return;
        }

        appendLogToContainer(
            waitingLogEl,
            eventType,
            eventMessage,
            Number(entry?.timestamp || 0),
            normalizeLogMarkerId(entry?.log_marker_id),
            normalizeEventId(entry?.event_id),
            Math.max(1, Number(entry?.event_revision || 1)),
            Math.max(0, Number(entry?.event_version || 0)),
        );
    });
}

async function fetchWebSocketTicket(clientId, nickname) {
    diagLog("api_ws_ticket_start", { client_id: clientId });
    const response = await fetch("/api/ws-ticket", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            client_id: clientId,
            nickname,
        }),
    });
    diagLog("api_ws_ticket_response", { status: response.status, ok: response.ok, client_id: clientId });

    if (!response.ok) {
        let detail = "";
        try {
            const errorPayload = await response.json();
            detail = String(errorPayload?.detail || "").trim();
        } catch {
            detail = "";
        }

        const error = new Error(`ws_ticket_request_failed:${response.status}`);
        error.status = response.status;
        error.detail = detail;
        throw error;
    }

    const payload = await response.json();
    const ticket = String(payload.ticket || "").trim();
    const sanitizedNickname = String(payload.nickname || nickname || "").trim() || "ゲスト";

    if (ticket === "") {
        throw new Error("ws_ticket_missing");
    }

    return {
        ticket,
        nickname: sanitizedNickname,
    };
}

function buildWebSocketUrl(clientId, nickname, wsTicket) {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = new URL(window.location.origin);
    wsUrl.protocol = wsProtocol;
    wsUrl.pathname = `/ws/${encodeURIComponent(clientId)}`;
    wsUrl.searchParams.set("nickname", nickname);
    wsUrl.searchParams.set("ws_ticket", wsTicket);
    return wsUrl.toString();
}

window.onload = () => {
    const savedNickname = localStorage.getItem("quiz_nickname");

    if (savedNickname) {
        document.getElementById("nickname").value = savedNickname;
    }

    const shouldAutoReconnect = localStorage.getItem("quiz_auto_reconnect") === "1";
    if (shouldAutoReconnect && savedNickname) {
        localStorage.removeItem("quiz_auto_reconnect");
        window.setTimeout(() => {
            document.getElementById("join-btn").click();
        }, 0);
    }
};

window.setInterval(() => {
    if (!isInGameArena()) {
        return;
    }
    updateArenaProgressAnnouncement();
}, 1000);

// 「ゲームに参加」ボタンを押したときの処理
document.getElementById("join-btn").addEventListener("click", async () => {
    if (isConnecting) {
        return;
    }

    const nicknameInput = document.getElementById("nickname").value.trim();
    if (nicknameInput === "") {
        await showAlertModal("ニックネームを入力してください");
        return;
    }

    isConnecting = true;
    const clientId = getOrCreatePersistentClientId();
    myClientId = clientId;

    let ticketPayload;
    try {
        ticketPayload = await fetchWebSocketTicket(clientId, nicknameInput);
    } catch (error) {
        console.error("WebSocket認証チケットの取得に失敗:", error);
        isConnecting = false;
        if (error?.status === 409 || error?.detail === "already_connected") {
            await showAlertModal("同じクライアントがすでに接続中です。\n\n別タブを閉じてから参加してください。");
        } else {
            await showAlertModal("接続認証の取得に失敗しました。時間をおいて再試行してください。");
        }
        return;
    }

    const effectiveNickname = ticketPayload.nickname;
    localStorage.setItem("quiz_nickname", effectiveNickname);
    document.getElementById("nickname").value = effectiveNickname;

    const wsUrl = buildWebSocketUrl(clientId, effectiveNickname, ticketPayload.ticket);
    diagLog("ws_connect_start", { client_id: clientId });
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        diagLog("ws_open", { client_id: clientId, ws: quizWsReadyStateLabel() });
        isConnecting = false;
        connectionTimeoutModalShown = false;
        localStorage.removeItem("quiz_auto_reconnect");
        console.log("サーバーに接続しました");
        document.getElementById("login-screen").style.display = "none";
        showWaitingRoomScreen();
        document.getElementById("my-name").textContent = effectiveNickname;
    };

    ws.onerror = () => {
        diagLog("ws_error", { client_id: clientId, ws: quizWsReadyStateLabel() });
        isConnecting = false;
        setAiQuestionLoading(false);
        if (!ws || ws.readyState === WebSocket.OPEN) return;
        void showConnectionTimeoutReloadModal();
    };

    ws.onclose = (event) => {
        diagLog("ws_close", {
            client_id: clientId,
            code: Number(event?.code || 0),
            reason: String(event?.reason || ""),
            ws: quizWsReadyStateLabel(),
        });
        isConnecting = false;
        setAiQuestionLoading(false);
        if (event.code === 1000) return;

        const friendlyMessage = getFriendlyConnectionErrorMessage(event);
        if (friendlyMessage) {
            closeAllModals();
            void showAlertModal(friendlyMessage);
            return;
        }

        if (!isLikelyConnectionTimeout(event)) return;
        void showConnectionTimeoutReloadModal();
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const prevChatRole = userRole;
        const prevRoomState = currentRoomGameState;
        const prevLeftCorrectWaiting = Boolean(currentGameState?.left_correct_waiting);
        currentRoomsSnapshot = Array.isArray(data.rooms) ? data.rooms : currentRoomsSnapshot;
        if (typeof data.ai_question_generation_active === "boolean") {
            aiQuestionGenerationActive = data.ai_question_generation_active;
        }
        if (Object.prototype.hasOwnProperty.call(data, "ai_question_generation_owner_id")) {
            aiQuestionGenerationOwnerId = data.ai_question_generation_owner_id || null;
        }

        updateAiQuestionButtonState(currentRoomsSnapshot);

        if (aiQuestionRequestPending) {
            const enteredArena = data.target_screen === "game_arena"
                && Boolean(data.current_room?.is_ai_mode)
                && String(data.current_room?.room_owner_id || "") === String(myClientId || "");
            const receivedPrivateError = data.event_type === "private_notice" && Boolean(data.private_info);
            const roomCreatedInLobby = Array.isArray(data.rooms)
                && data.rooms.some((room) => String(room?.room_owner_id || "") === String(myClientId || ""));
            if (enteredArena || receivedPrivateError || roomCreatedInLobby) {
                setAiQuestionLoading(false);
            }
        }

        if (isKifuMode) {
            return;
        }
        const eventMessageForLog = String(data.event_message || data.public_info || "").trim();
        const incomingEventId = normalizeEventId(data.event_id || data.event_payload?.event_id);
        const incomingEventRevision = Math.max(1, Number(data.event_revision || data.event_payload?.event_revision || 1));
        const incomingEventRecord = normalizeArenaEventRecord({
            ...data,
            event_message: eventMessageForLog,
            event_id: incomingEventId,
            event_revision: incomingEventRevision,
        });
        const wasInArena = isInGameArena();
        hydrateLobbyChatHistoryIfNeeded(data.lobby_chat_history);
        currentRoomSnapshot = data.current_room ?? null;
        userRole = data.current_room?.chat_role ?? null;
        currentRoomGameState = data.current_room?.game_state ?? null;
        currentGameState = data.current_room?.game ?? null;
        const activeRoomId = String(data.current_room?.room_owner_id || "").trim() || null;
        if (isArenaReplayMode && (!activeRoomId || activeRoomId !== currentArenaReplayRoomId || currentRoomGameState !== "finished")) {
            clearReplayState();
        }
        const shouldRevealFinishedArenaLogs = data.event_type === "game_finished"
            || (currentRoomGameState === "finished" && previousRoomGameState !== "finished");
        const shouldReconcileArenaLogsOnGameStart = data.event_type === "game_start"
            && Boolean(activeRoomId)
            && String(currentRoomGameState || "") === "playing";

        const isEnteringArena = data.target_screen === "game_arena" && (!wasInArena || activeRoomId !== currentArenaLogRoomId);
        const isLeavingArena = wasInArena && data.target_screen === "waiting_room";
        const shouldRebuildArenaLogs = isEnteringArena;

        debugArenaHistory("ws.onmessage decision", {
            eventType: data.event_type || null,
            targetScreen: data.target_screen || null,
            activeRoomId,
            wasInArena,
            currentArenaLogRoomId,
            isEnteringArena,
            isLeavingArena,
            shouldRebuildArenaLogs,
        });

        if (isEnteringArena || isLeavingArena) {
            resetArenaChatCaches();
        }

        if (shouldRebuildArenaLogs && activeRoomId) {
            hydrateArenaChatHistoryIfNeeded(data.current_room);
            hydratePreGameGlobalHistoryIfNeeded(data.current_room);
            renderArenaLogsForRoom(activeRoomId, { forceScrollToBottom: true });
            debugArenaHistory("ws.onmessage rebuilt from snapshot", {
                roomId: activeRoomId,
                reason: "shouldRebuildArenaLogs",
            });
        }

        if (shouldRevealFinishedArenaLogs && activeRoomId) {
            hydrateArenaChatHistoryIfNeeded(data.current_room);
            hydratePreGameGlobalHistoryIfNeeded(data.current_room);
            renderArenaLogsForRoom(activeRoomId, { forceScrollToBottom: true });
            debugArenaHistory("ws.onmessage revealed finished arena logs", {
                roomId: activeRoomId,
                reason: "game_finished",
            });
        }

        if (shouldReconcileArenaLogsOnGameStart && activeRoomId) {
            hydrateArenaChatHistoryIfNeeded(data.current_room);
            hydratePreGameGlobalHistoryIfNeeded(data.current_room);
            renderArenaLogsForRoom(activeRoomId, { forceScrollToBottom: true });
            debugArenaHistory("ws.onmessage reconciled arena logs", {
                roomId: activeRoomId,
                reason: "game_start",
            });
        }

        document.body.dataset.chatRole = String(userRole || "");
        document.body.dataset.roomRole = String(data.current_room?.role || "");

        if (data.target_screen === "game_arena") {
            updateArenaLeaveLabel(data.current_room);
            showGameArenaScreen();
        } else if (data.target_screen === "waiting_room") {
            pendingArenaMode = null;
            updateArenaLeaveLabel("guest");
            showWaitingRoomScreen();
        }

        if (data.event_type === "game_finished") {
            closeAllModals();
            void showAlertModal(buildGameFinishedAlertMessage(data));
        } else if (data.event_type === "forced_exit_notice" && data.private_info) {
            closeAllModals();
            void showConfirmModal(data.private_info, { hideCancel: true, okLabel: "OK" });
        } else if (data.event_type === "private_notice" && data.private_info) {
            closeAllModals();
            void showAlertModal(data.private_info);
        }

        // 投票が解決されたらハンドル状態を解放し、再提案/再投票を阻害しないようにする。
        if (data.event_type === "open_vote_resolved") {
            const resolvedVoteId = String(data.event_payload?.vote_id || "");
            if (resolvedVoteId !== "") {
                handledOpenVoteIds.delete(resolvedVoteId);
            }
        }
        if (data.event_type === "answer_vote_resolved") {
            const resolvedVoteId = String(data.event_payload?.vote_id || "");
            if (resolvedVoteId !== "") {
                handledAnswerVoteIds.delete(resolvedVoteId);
            }
        }
        if (data.event_type === "turn_end_vote_resolved") {
            const resolvedVoteId = String(data.event_payload?.vote_id || "");
            if (resolvedVoteId !== "") {
                handledTurnEndVoteIds.delete(resolvedVoteId);
            }
        }
        if (data.event_type === "intentional_draw_vote_resolved") {
            const resolvedVoteId = String(data.event_payload?.vote_id || "");
            if (resolvedVoteId !== "") {
                handledIntentionalDrawVoteIds.delete(resolvedVoteId);
            }
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
        if (data.event_type === "intentional_draw_vote_request" && data.event_payload) {
            void handleIntentionalDrawVoteRequest(data.event_payload);
        }
        if (data.event_type === "answer_judgement_request" && data.event_payload) {
            void handleAnswerJudgementRequest(data.event_payload);
        }

        const displayMessage = getArenaDisplayedMessageForViewer(incomingEventRecord);

        // 入室時の履歴再描画を除き、受信イベントは増分で追記する。
        if (!isEnteringArena && !shouldReconcileArenaLogsOnGameStart) {
            // Determine log marker ID
            let logMarkerId = incomingEventRecord.logMarkerId;
            if ((incomingEventRecord.eventType === "answer_vote_request" || incomingEventRecord.eventType === "answer_vote_resolved"
                || incomingEventRecord.eventType === "open_vote_request" || incomingEventRecord.eventType === "open_vote_resolved"
                || incomingEventRecord.eventType === "turn_end_vote_request" || incomingEventRecord.eventType === "turn_end_vote_resolved"
                || incomingEventRecord.eventType === "intentional_draw_vote_request" || incomingEventRecord.eventType === "intentional_draw_vote_resolved")
                && data.event_payload?.vote_id) {
                logMarkerId = normalizeLogMarkerId(data.event_payload.vote_id);
            }
            appendEventLog(
                incomingEventRecord.eventType,
                displayMessage,
                incomingEventRecord.eventChatType,
                incomingEventRecord.roomId,
                incomingEventRecord.eventTimestamp,
                logMarkerId,
                incomingEventId,
                incomingEventRevision,
                incomingEventRecord.eventVersion,
            );
        }
        renderRooms(data.rooms);
        renderParticipants(data.participants);
        renderArena(data.current_room);
        updateGameStateUI();
        updateStartGameButtonVisibility(data.current_room);
        updateArenaCloseButtonVisibility(data.current_room);
        if (isInGameArena()) {
            updateArenaLeaveLabel(data.current_room);
        }
        updateArenaAnswerFormVisibility();
        updateChatBoxVisibility();

        const isPlayingParticipantJoin = isEnteringArena
            && String(data.current_room?.role || "") === "participant"
            && String(currentRoomGameState || "") === "playing";
        if (isEnteringArena && !isPlayingParticipantJoin) {
            enableArenaProgressChatFilter();
        }

        const reachedGameFinished = String(currentRoomGameState || "") === "finished"
            && String(prevRoomState || "") !== "finished";
        const reachedLeftRevealWindow = String(currentRoomGameState || "") === "playing"
            && String(userRole || "") === "team-left"
            && Boolean(currentGameState?.left_correct_waiting)
            && (
                String(prevRoomState || "") !== "playing"
                || String(prevChatRole || "") !== "team-left"
                || !prevLeftCorrectWaiting
            );
        if (reachedGameFinished || reachedLeftRevealWindow) {
            enableArenaProgressChatFilter();
        }

        if (reachedLeftRevealWindow && activeRoomId) {
            // 先攻正解後の後攻アンサー待ちに入ったタイミングで、閲覧可能範囲が広がるため履歴を再構築する。
            hydrateArenaChatHistoryIfNeeded(data.current_room);
            renderArenaLogsForRoom(activeRoomId);
            debugArenaHistory("ws.onmessage rebuilt logs for left reveal window", {
                roomId: activeRoomId,
                reason: "left_correct_waiting_entered",
            });
        }

        if (!isKifuMode && currentRoomGameState === "finished") {
            if (isArenaReplayMode && activeRoomId === currentArenaReplayRoomId && Array.isArray(currentKifuSteps) && currentKifuSteps.length > 0) {
                renderKifuStep();
            } else {
                void startFinishedArenaReplay(data.current_room);
            }
        }
    };
});

document.getElementById("nickname").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    document.getElementById("join-btn").click();
});

async function submitQuestion() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!questionInputEl) return;

    const questionText = questionInputEl.value.trim();
    if (questionText === "") {
        await showAlertModal("問題を入力してください");
        return;
    }

    const normalizedQuestionLength = countNormalizedQuestionChars(questionText);
    if (normalizedQuestionLength > QUESTION_MAX_LENGTH) {
        await showAlertModal(`問題文は${QUESTION_MAX_LENGTH}文字以内で入力してください`);
        return;
    }

    const confirmResult = await showQuestionConfirmModal(questionText);
    if (!confirmResult || !confirmResult.confirmed) {
        return;
    }
    const normalizedGenre = String(confirmResult.genre || "").trim().slice(0, 40);

    const questionPayload = {
        type: "question_submission",
        question_text: questionText,
        genre: normalizedGenre,
        timestamp: Date.now()
    };

    pendingArenaMode = "owner";
    ws.send(JSON.stringify(questionPayload));
    questionInputEl.value = "";
    updateQuestionLengthWarning();
}

async function submitAiQuestion() {
    if (aiQuestionRequestPending) {
        return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const selection = await showAiGenreInputModal();
    if (selection === null) {
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const normalizedGenre = String(selection.genre || "").trim().slice(0, 40);
    const normalizedModelId = String(selection.modelId || defaultAiModelId).trim() || defaultAiModelId;
    const normalizedAccuracyRate = normalizeAiAccuracyRate(selection.accuracyRate);
    setAiQuestionLoading(true);
    pendingArenaMode = "owner";

    ws.send(
        JSON.stringify({
            type: "question_submission",
            is_ai_mode: true,
            genre: normalizedGenre,
            model_id: normalizedModelId,
            difficulty: normalizedAccuracyRate,
            accuracy_rate: normalizedAccuracyRate,
            timestamp: Date.now(),
        })
    );
}

document.getElementById("submit-question-btn").addEventListener("click", () => {
    submitQuestion();
});

aiQuestionBtnEl?.addEventListener("click", () => {
    void submitAiQuestion();
});

questionInputEl?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    submitQuestion();
});

questionInputEl?.addEventListener("input", () => {
    updateQuestionLengthWarning();
});

async function requestRoomExit() {
    if (isKifuMode) {
        exitKifuViewerToList();
        return;
    }

    const snapshot = currentRoomSnapshot;
    const ownerId = String(snapshot?.room_owner_id || "");
    const me = String(myClientId || "");
    const isOwner = ownerId !== "" && me !== "" && ownerId === me;
    const isAiRoom = Boolean(snapshot?.is_ai_mode);
    const shouldCloseRoom = isOwner && !isAiRoom;

    const confirmMessage = shouldCloseRoom
        ? "部屋を閉じると参加者と観戦者は全員退室になります。\n\n本当に部屋を閉じますか？"
        : "本当に退室しますか？";
    const okLabel = shouldCloseRoom ? "部屋を閉じる" : "退室する";

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

    // 送信直後は該当ログ欄を下端へ寄せる。
    const targetLogId = chatType === "lobby" ? "event-log" : `game-chat-log-${chatType}`;
    const targetLogEl = document.getElementById(targetLogId);
    const scrollContainer = resolveLogScrollContainer(targetLogEl);
    if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
        const indicatorEl = ensureLogNewIndicator(scrollContainer);
        if (indicatorEl) {
            indicatorEl.classList.add("hidden");
        }
    }

    lastChatSentAt[chatType] = now;
    inputEl.value = "";
    autoResizeChatInput(inputEl);
    updateChatLengthWarning(inputEl);
}

function bindChatHandlers() {
    // イベント委譲：全チャットボックスの送信ボタン
    document.addEventListener("click", (event) => {
        const sendBtn = event.target.closest?.(".chat-send-btn, .lobby-chat-send-btn, .arena-chat-send-btn");
        if (!sendBtn) {
            return;
        }

        const chatBox = sendBtn.closest(".chat-box");
        if (chatBox) {
            sendChatMessage(chatBox);
        }
    });

    // イベント委譲：全チャットボックスの入力欄
    document.addEventListener("input", (event) => {
        if (event.target.classList.contains("chat-input")) {
            autoResizeChatInput(event.target);
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
initChatLogFilterControls();

document.querySelectorAll(".chat-input").forEach((inputEl) => {
    autoResizeChatInput(inputEl);
});

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
        await showAlertModal("オープン処理中です。少し時間を空けてください。");
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        await showAlertModal("サーバー接続後に操作できます");
        return;
    }

    const teamParticipantCount = getCurrentTeamParticipantCount();
    const isProposalMode = teamParticipantCount > 1;
    const finalChanceWarning = isRightFinalActionBeforeOpen()
        ? "\n\nこのオープンで後攻のアクション権が尽きるため、この時点で先攻の勝利になります。実行しますか？"
        : "";
    if (isProposalMode) {
        const confirmed = await showConfirmModal(
            `${charIndex + 1}文字目オープンを提案しますか？${finalChanceWarning}`,
            {
                okLabel: "提案する",
                cancelLabel: "キャンセル",
            }
        );
        if (!confirmed) {
            return;
        }
    } else if (finalChanceWarning !== "") {
        const confirmed = await showConfirmModal(
            `${charIndex + 1}文字目をオープンします。${finalChanceWarning}`,
            {
                okLabel: "オープンする",
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
    const targetTeam = String(payload?.team || "").trim();
    const isResend = payload?.resend === true;
    if (targetTeam !== "team-left" && targetTeam !== "team-right") return;
    if (userRole !== targetTeam) return;
    if (!voteId || !Number.isFinite(charIndex)) return;
    if (isResend) {
        handledOpenVoteIds.delete(voteId);
    }
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
        handledOpenVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。再接続後にもう一度回答してください。");
        return;
    }

    try {
        ws.send(
            JSON.stringify({
                type: "open_vote_response",
                vote_id: voteId,
                approve: Boolean(confirmed),
                timestamp: Date.now()
            })
        );
    } catch {
        handledOpenVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。もう一度回答してください。");
    }
}

async function handleAnswerVoteRequest(payload) {
    const voteId = String(payload?.vote_id || "");
    const payloadTeam = String(payload?.team || "");
    const teamLabel = String(payload?.team_label || "");
    const answererName = String(payload?.answerer_name || "参加者");
    const answerText = String(payload?.answer_text || "");
    const totalVoters = Number(payload?.total_voters || 0);
    const isResend = payload?.resend === true;

    if (!voteId) return;
    if (isPlayerRole(userRole) && payloadTeam && payloadTeam !== userRole) return;
    if (!answerText) return;
    if (isResend) {
        handledAnswerVoteIds.delete(voteId);
    }
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
        handledAnswerVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。再接続後にもう一度回答してください。");
        return;
    }

    try {
        ws.send(
            JSON.stringify({
                type: "answer_vote_response",
                vote_id: voteId,
                approve: Boolean(confirmed),
                timestamp: Date.now(),
            })
        );
    } catch {
        handledAnswerVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。もう一度回答してください。");
    }
}

async function handleTurnEndVoteRequest(payload) {
    const voteId = String(payload?.vote_id || "");
    const teamLabel = String(payload?.team_label || "");
    const totalVoters = Number(payload?.total_voters || 0);
    const isResend = payload?.resend === true;
    if (!voteId) return;
    if (isResend) {
        handledTurnEndVoteIds.delete(voteId);
    }
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
        handledTurnEndVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。再接続後にもう一度回答してください。");
        return;
    }

    try {
        ws.send(
            JSON.stringify({
                type: "turn_end_vote_response",
                vote_id: voteId,
                approve: Boolean(confirmed),
                timestamp: Date.now(),
            })
        );
    } catch {
        handledTurnEndVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。もう一度回答してください。");
    }
}

async function handleIntentionalDrawVoteRequest(payload) {
    const voteId = String(payload?.vote_id || "");
    const totalVoters = Number(payload?.total_voters || 0);
    const requesterName = String(payload?.requester_name || "参加者");
    const isResend = payload?.resend === true;
    if (!voteId) return;
    if (isResend) {
        handledIntentionalDrawVoteIds.delete(voteId);
    }
    if (handledIntentionalDrawVoteIds.has(voteId)) return;
    handledIntentionalDrawVoteIds.add(voteId);

    const unanimityNote = totalVoters > 1
        ? "\n（全員のOKで成立します）"
        : "";
    const confirmed = await showConfirmModal(
        `${requesterName}によりIDが提案されました。\nID(インテンショナルドロー)に同意しますか？${unanimityNote}`,
        {
            okLabel: "同意する",
            cancelLabel: "同意しない",
        }
    );

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        handledIntentionalDrawVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。再接続後にもう一度回答してください。");
        return;
    }

    try {
        ws.send(
            JSON.stringify({
                type: "intentional_draw_vote_response",
                vote_id: voteId,
                approve: Boolean(confirmed),
                timestamp: Date.now(),
            })
        );
    } catch {
        handledIntentionalDrawVoteIds.delete(voteId);
        await showAlertModal("投票送信に失敗しました。もう一度回答してください。");
    }
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
            requireExplicitChoice: true,
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
    if (isReplayMode() && isInGameArena()) {
        if (event.key === "ArrowLeft") {
            event.preventDefault();
            currentKifuStepIndex = Math.max(0, currentKifuStepIndex - 1);
            renderKifuStep();
            return;
        }
        if (event.key === "ArrowRight") {
            event.preventDefault();
            currentKifuStepIndex = Math.min(Math.max(0, currentKifuSteps.length - 1), currentKifuStepIndex + 1);
            renderKifuStep();
            return;
        }
    }

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

document.getElementById("arena-logs-close-btn")?.addEventListener("click", () => {
    closeArenaLogsPresentation();
});

arenaLogsModalEl?.addEventListener("click", (event) => {
    if (event.target === arenaLogsModalEl) {
        closeArenaLogsPresentation();
    }
});

arenaAnswerSubmitBtnEl?.addEventListener("click", () => {
    void submitArenaAnswer();
});

arenaTurnEndBtnEl?.addEventListener("click", () => {
    void submitTurnEndAttempt();
});

arenaIntentionalDrawBtnEl?.addEventListener("click", () => {
    void submitIntentionalDrawProposal();
});

arenaAnswerInputEl?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) {
        return;
    }

    event.preventDefault();
    void submitArenaAnswer();
});

arenaAnswerInputEl?.addEventListener("input", () => {
    updateArenaAnswerLengthWarning();
});

document.addEventListener("click", (event) => {
    const toggleBtnEl = document.getElementById("arena-logs-toggle-btn");
    if (!arenaLogsModalEl || !toggleBtnEl || !arenaLogsModalEl.open) return;

    const isClickInside = arenaLogsModalEl.contains(event.target) || toggleBtnEl.contains(event.target);
    if (!isClickInside) {
        closeArenaLogsPresentation();
    }
});

window.addEventListener("resize", () => {
    syncArenaPlayerBoxHeights();
    if (isInGameArena()) {
        renderArenaQuestionText();
        syncArenaLogsPresentation();
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

document.getElementById("arena-logs-toggle-btn")?.addEventListener("click", () => {
    if (!arenaGlobalChatBoxEl) return;

    if (isMobileArenaLogsMode()) {
        if (arenaLogsModalEl?.open) {
            closeArenaLogsPresentation();
            return;
        }

        mountArenaLogsIntoModal();
        arenaLogsModalEl?.showModal();
        return;
    }

    arenaGlobalChatBoxEl.classList.toggle("open");
});

closeRoomBtnEl?.addEventListener("click", () => {
    void requestCloseRoom(currentRoomSnapshot?.room_owner_id);
});

closeRoomBtnEl?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        void requestCloseRoom(currentRoomSnapshot?.room_owner_id);
    }
});

openKifuListBtnEl?.addEventListener("click", async () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        void showAlertModal("サーバー接続後に利用できます");
        return;
    }
    try {
        currentKifuList = await fetchKifuList();
        renderKifuListRows(currentKifuList);
        showKifuListScreen();
    } catch {
        void showAlertModal("棋譜一覧の読み込みに失敗しました。");
    }
});

kifuListBackLinkEl?.addEventListener("click", () => {
    showWaitingRoomScreen();
});

kifuListBackLinkEl?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        showWaitingRoomScreen();
    }
});

kifuStepPrevBtnEl?.addEventListener("click", () => {
    currentKifuStepIndex = Math.max(0, currentKifuStepIndex - 1);
    renderKifuStep();
});

kifuStepNextBtnEl?.addEventListener("click", () => {
    currentKifuStepIndex = Math.min(Math.max(0, currentKifuSteps.length - 1), currentKifuStepIndex + 1);
    renderKifuStep();
});

kifuStepFirstBtnEl?.addEventListener("click", () => {
    currentKifuStepIndex = 0;
    renderKifuStep();
});

kifuStepLastBtnEl?.addEventListener("click", () => {
    currentKifuStepIndex = Math.max(0, currentKifuSteps.length - 1);
    renderKifuStep();
});

function showRulebookModal(triggerEl = null) {
    if (!rulebookModalEl) return;
    if (triggerEl instanceof HTMLElement) {
        lastRulebookTriggerEl = triggerEl;
    }
    if (!rulebookModalEl.open) {
        rulebookModalEl.showModal();
    }
    updateArenaInteractionLock();
    rulebookCloseBtnEl?.focus();
}

function closeRulebookModal() {
    if (!rulebookModalEl) return;
    setArenaCharClickGuard();
    if (rulebookModalEl.open) {
        rulebookModalEl.close();
    }
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

        rulebookModalEl.addEventListener("cancel", (event) => {
            event.preventDefault();
            closeRulebookModal();
        });
    }
}

bindRulebookHandlers();
updateQuestionLengthWarning();
updateArenaAnswerLengthWarning();
updateViewportDebugOverlay();

