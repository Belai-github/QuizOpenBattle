let ws;

window.onload = () => {
    const savedNickname = localStorage.getItem("quiz_nickname");

    if (savedNickname) {
        document.getElementById("nickname").value = savedNickname;
    }
};

// 「ゲームに参加」ボタンを押したときの処理
document.getElementById("join-btn").addEventListener("click", () => {
    const nicknameInput = document.getElementById("nickname").value.trim();
    if (nicknameInput === "") {
        alert("ニックネームを入力してください");
        return;
    }
    localStorage.setItem("quiz_nickname", nicknameInput);

    const clientId = crypto.randomUUID();

    const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    const encodedName = encodeURIComponent(nicknameInput);
    ws = new WebSocket(`${protocol}${window.location.host}/ws/${clientId}?nickname=${encodedName}`);

    ws.onopen = () => {
        console.log("サーバーに接続しました");
        document.getElementById("login-screen").style.display = "none";
        document.getElementById("game-screen").style.display = "block";
        document.getElementById("my-name").textContent = nicknameInput;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        document.getElementById("public-info").textContent = data.public_info;
        document.getElementById("private-info").textContent = data.private_info;
    };
});

document.getElementById("action-btn").addEventListener("click", () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    const answerInput = document.getElementById("answer-box");
    const actionData = {
        action: "解答",
        content: answerInput.value,
        timestamp: Date.now()
    };

    ws.send(JSON.stringify(actionData));
    answerInput.value = "";
});
