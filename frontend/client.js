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
const lobbyChatInputEl = document.getElementById("lobby-chat-input");
const lobbyChatSendBtnEl = document.getElementById("lobby-chat-send-btn");

let pendingArenaMode = null;

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
}

function showGameArenaScreen() {
    document.getElementById("waiting-room-screen").style.display = "none";
    document.getElementById("game-arena-screen").style.display = "block";
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

    names.forEach((name) => {
        const item = document.createElement("li");
        item.textContent = name;
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

    titleEl.textContent = `出題者: ${currentRoom.questioner_name}`;
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

function appendEventLog(eventType, eventMessage) {
    const allowedTypes = new Set(["join", "leave", "question", "chat"]);
    if (!allowedTypes.has(eventType) || !eventMessage) {
        return;
    }

    const logEl = document.getElementById("event-log");
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
    logEl.appendChild(item);

    while (logEl.children.length > 50) {
        logEl.removeChild(logEl.firstChild);
    }

    const logBoxEl = document.getElementById("event-log-box");
    logBoxEl.scrollTop = logBoxEl.scrollHeight;
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

        appendEventLog(data.event_type, data.event_message);
        renderRooms(data.rooms);
        renderParticipants(data.participants);
        renderArena(data.current_room);
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

function requestRoomExit() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "room_exit" }));
    }
    pendingArenaMode = null;
    updateArenaLeaveLabel("guest");
    showWaitingRoomScreen();
}

function sendLobbyChatMessage() {
    if (!lobbyChatInputEl) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        void showAlertModal("サーバー接続後にチャットを送信できます");
        return;
    }

    const message = lobbyChatInputEl.value.trim();
    if (message === "") return;

    ws.send(
        JSON.stringify({
            type: "chat_message",
            message,
            timestamp: Date.now()
        })
    );
    lobbyChatInputEl.value = "";
}

function bindLobbyChatHandlers() {
    if (lobbyChatSendBtnEl) {
        lobbyChatSendBtnEl.addEventListener("click", () => {
            sendLobbyChatMessage();
        });
    }

    if (lobbyChatInputEl) {
        lobbyChatInputEl.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
            event.preventDefault();
            sendLobbyChatMessage();
        });
    }
}

bindLobbyChatHandlers();

leaveGameArenaEl?.addEventListener("click", requestRoomExit);
leaveGameArenaEl?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        requestRoomExit();
    }
});
