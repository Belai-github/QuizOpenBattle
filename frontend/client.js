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
const rulebookTriggerEls = document.querySelectorAll(".rulebook-trigger");
const rulebookModalEl = document.getElementById("rulebook-modal");
const rulebookContentEl = document.getElementById("rulebook-content");
const rulebookCloseBtnEl = document.getElementById("rulebook-close-btn");

let pendingArenaMode = null;
let userRole = null; // "questioner", "team-left", "team-right", "spectator", null
const CHAT_MAX_LENGTH = 200;
const CHAT_MIN_INTERVAL_MS = 800;
const lastChatSentAt = {}; // key: "lobby" or "game-all", "team-left", "team-right", "questioner"
let lastRulebookTriggerEl = null;

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

function updateChatBoxVisibility() {
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
        leaveGameArenaEl.textContent = "☓部屋を閉じる";
        leaveGameArenaEl.setAttribute("aria-label", "部屋を閉じる");
        return;
    }

    leaveGameArenaEl.textContent = "←退室";
    leaveGameArenaEl.setAttribute("aria-label", "退室");
}

function showWaitingRoomScreen() {
    document.getElementById("waiting-room-screen").style.display = "block";
    document.getElementById("game-arena-screen").style.display = "none";
    updateChatBoxVisibility();
}

function showGameArenaScreen() {
    document.getElementById("waiting-room-screen").style.display = "none";
    document.getElementById("game-arena-screen").style.display = "block";
    updateChatBoxVisibility();
}

function showAlertModal(message) {
    return new Promise((resolve) => {
        alertMessageEl.textContent = message;
        alertModal.classList.remove("hidden");
        alertOkBtn.focus();

        const close = () => {
            alertModal.classList.add("hidden");
            alertOkBtn.removeEventListener("click", onOk);
            alertModal.removeEventListener("click", onBackdropClick);
            document.removeEventListener("keydown", onEscape);
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

        const close = (result) => {
            confirmModal.classList.add("hidden");
            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancel);
            confirmModal.removeEventListener("click", onBackdropClick);
            document.removeEventListener("keydown", onEscape);
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

        const close = (result) => {
            confirmModal.classList.add("hidden");
            confirmCancelBtn.style.display = "";
            confirmActionsEl.classList.remove("single");
            confirmOkBtn.textContent = "送信する";
            confirmCancelBtn.textContent = "キャンセル";
            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancel);
            confirmModal.removeEventListener("click", onBackdropClick);
            document.removeEventListener("keydown", onEscape);
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

function renderArena(currentRoom) {
    const titleEl = document.getElementById("arena-room-title");
    const questionEl = document.getElementById("arena-question-text");
    const leftListEl = document.getElementById("arena-player-left-list");
    const rightListEl = document.getElementById("arena-player-right-list");
    const spectatorListEl = document.getElementById("arena-spectator-list");

    if (!currentRoom) {
        titleEl.textContent = "出題者: -";
        questionEl.textContent = "問題文を準備中...";
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
    questionEl.textContent = currentRoom.question_text || "問題文を準備中...";

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
        metaEl.textContent = `参加 ${room.participant_count}人 / 観戦 ${room.spectator_count}人`;

        if (!room.is_owner) {
            const actionsEl = document.createElement("div");
            actionsEl.className = "room-card-actions";

            const joinBtn = document.createElement("button");
            joinBtn.type = "button";
            joinBtn.className = "room-card-btn";
            joinBtn.textContent = "参加";

            const watchBtn = document.createElement("button");
            watchBtn.type = "button";
            watchBtn.className = "room-card-btn secondary";
            watchBtn.textContent = "観戦";

            joinBtn.addEventListener("click", () => requestRoomEntry(room.room_owner_id, "participant"));
            watchBtn.addEventListener("click", () => requestRoomEntry(room.room_owner_id, "spectator"));

            actionsEl.appendChild(joinBtn);
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
    const allowedTypes = new Set(["join", "leave", "question", "chat"]);
    if (!allowedTypes.has(eventType) || !eventMessage) {
        return;
    }

    if (eventType === "chat" && eventChatType && eventChatType !== "lobby") {
        const roomLogEl = document.getElementById(`game-chat-log-${eventChatType}`);
        appendLogToContainer(roomLogEl, eventType, eventMessage);
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
        userRole = data.current_room?.chat_role ?? null;
        if (data.target_screen === "game_arena") {
            updateArenaLeaveLabel(pendingArenaMode === "owner" ? "owner" : "guest");
            showGameArenaScreen();
        } else if (data.target_screen === "waiting_room") {
            pendingArenaMode = null;
            updateArenaLeaveLabel("guest");
            showWaitingRoomScreen();
        }

        if (data.event_type === "forced_exit_notice" && data.private_info) {
            void showConfirmModal(data.private_info, { hideCancel: true, okLabel: "OK" });
        } else if (data.event_type === "private_notice" && data.private_info) {
            void showAlertModal(data.private_info);
        }

        appendEventLog(data.event_type, data.event_message, data.event_chat_type);
        renderRooms(data.rooms);
        renderParticipants(data.participants);
        renderArena(data.current_room);
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

window.addEventListener("resize", () => {
    syncArenaPlayerBoxHeights();
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
    rulebookCloseBtnEl?.focus();
}

function closeRulebookModal() {
    if (!rulebookModalEl) return;
    rulebookModalEl.classList.add("hidden");
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
