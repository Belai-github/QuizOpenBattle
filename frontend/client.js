let ws; // WebSocketを変数として準備しておく

// 「ゲームに参加」ボタンを押したときの処理
document.getElementById("join-btn").addEventListener("click", () => {
    // 1. ニックネームを取得
    const nicknameInput = document.getElementById("nickname").value.trim();

    // 空欄の場合はアラートを出して止める
    if (nicknameInput === "") {
        alert("ニックネームを入力してください");
        return;
    }

    // 2. 入力されたニックネームをIDとしてWebSocket接続
    const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(`${protocol}${window.location.host}/ws/${nicknameInput}`);

    // 3. 接続が成功したときの処理
    ws.onopen = () => {
        console.log("サーバーに接続しました");
        // ログイン画面を隠して、ゲーム画面を表示する
        document.getElementById("login-screen").style.display = "none";
        document.getElementById("game-screen").style.display = "block";
        // 画面に自分の名前を表示
        document.getElementById("my-name").textContent = nicknameInput;
    };

    // 4. サーバーからメッセージを受け取ったときの処理
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        document.getElementById("public-info").textContent = data.public_info;
        document.getElementById("private-info").textContent = data.private_info;
    };
});

// 「解答を送信」ボタンを押したときの処理
document.getElementById("action-btn").addEventListener("click", () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return; // 接続されていなければ何もしない

    const answerInput = document.getElementById("answer-box");
    const actionData = {
        action: "解答",
        content: answerInput.value,
        timestamp: Date.now()
    };

    ws.send(JSON.stringify(actionData));
    answerInput.value = ""; // 送信後にテキストボックスを空にする
});
