const CLIENT_ID_KEY = "qob_client_id";
const NICKNAME_KEY = "qob_nickname";

let clientId = localStorage.getItem(CLIENT_ID_KEY);
if (!clientId) {
    clientId = crypto.randomUUID();
    localStorage.setItem(CLIENT_ID_KEY, clientId);
}

const ws = new WebSocket(`ws://${location.host}/ws/${clientId}`);

ws.addEventListener("open", () => {
    const cachedName = localStorage.getItem(NICKNAME_KEY);
    if (cachedName) {
        ws.send(JSON.stringify({ type: "set_nickname", nickname: cachedName }));
    }
    ws.send(JSON.stringify({ type: "get_participants" }));
});

function saveNickname(name) {
    localStorage.setItem(NICKNAME_KEY, name);
    ws.send(JSON.stringify({ type: "set_nickname", nickname: name }));
}

ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "participants") {
        // msg.participants を画面に表示
        // 例: [{ client_id: "...", nickname: "Alice" }, ...]
    }
});
