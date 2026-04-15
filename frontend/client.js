let ws;
let myClientId = null;

const confirmModal = document.getElementById("confirm-modal");
const confirmMessageEl = document.getElementById("confirm-message");
const confirmOkBtn = document.getElementById("confirm-ok-btn");
const confirmCancelBtn = document.getElementById("confirm-cancel-btn");
const alertModal = document.getElementById("alert-modal");
const alertMessageEl = document.getElementById("alert-message");
const alertOkBtn = document.getElementById("alert-ok-btn");

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
        confirmMessageEl.textContent = `以下の問題文で出題しますか？\n\nQ.${questionText}`;
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

function appendEventLog(eventType, eventMessage) {
    const allowedTypes = new Set(["join", "leave", "question"]);
    if (!allowedTypes.has(eventType) || !eventMessage) {
        return;
    }

    const logEl = document.getElementById("event-log");
    const item = document.createElement("li");
    item.textContent = eventMessage;
    logEl.appendChild(item);

    while (logEl.children.length > 50) {
        logEl.removeChild(logEl.firstChild);
    }
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
        document.getElementById("game-screen").style.display = "block";
        document.getElementById("my-name").textContent = nicknameInput;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        appendEventLog(data.event_type, data.event_message);
        renderParticipants(data.participants);
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

    ws.send(JSON.stringify(questionPayload));
    questionInput.value = "";
}

document.getElementById("submit-question-btn").addEventListener("click", () => {
    submitQuestion();
});

document.getElementById("question-box").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    submitQuestion();
});
