// テスト用にランダムなIDを生成（本来はログインやルーム入室時に決める）
const clientId = "Player_" + Math.floor(Math.random() * 1000);
document.getElementById("my-id").textContent = clientId;

// WebSocketでPythonサーバーに接続
const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(`${protocol}${window.location.host}/ws/${clientId}`);

ws.onopen = () => {
    console.log("サーバーに接続しました");
};

// サーバーからメッセージを受け取ったときの処理
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // 画面の表示を更新（ここで非対称情報が反映される）
    document.getElementById("public-info").textContent = data.public_info;
    document.getElementById("private-info").textContent = data.private_info;
};

// ボタンを押したときの処理
document.getElementById("action-btn").addEventListener("click", () => {
    const actionData = {
        action: "攻撃", // テスト用のダミーデータ
        timestamp: Date.now()
    };
    // サーバーへ送信
    ws.send(JSON.stringify(actionData));
});
