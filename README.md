# QuizOpenBattle

> ブラウザで遊べる、リアルタイム対戦型のクイズゲーム。
> ルームを作成し、出題・参加・観戦を行いながら、先攻・後攻に分かれて対戦できます。

[![Demo](https://img.shields.io/badge/demo-<YOUR_DEMO_LABEL>-0f766e)](<YOUR_DEMO_URL>)
[![License](https://img.shields.io/badge/license-<YOUR_LICENSE>-2563eb)](./LICENSE)

## スクリーンショット

| ロビー | アリーナ |
|---|---|
| ![Lobby](<YOUR_SCREENSHOT_LOBBY_PATH>) | ![Arena](<YOUR_SCREENSHOT_ARENA_PATH>) |

## 概要

QuizOpenBattle は、ブラウザ上で遊べるリアルタイム対戦型のクイズゲームです。
ルームを作成して問題を出題し、参加者が先攻・後攻に分かれて対戦できます。
ログインなしのゲスト参加にも対応していますが、ログインすると戦績管理や棋譜閲覧などのアカウント機能を利用できます。

ルールの詳細はゲーム内のルールブック、または [`RULES.md`](./RULES.md) を参照してください。

---

## 主な機能

- ブラウザだけで遊べるリアルタイム対戦
- 出題ルーム作成・参加・観戦
- ゲスト参加対応
- パスキー（WebAuthn）によるログイン
- 戦績管理
- 棋譜閲覧
- WebSocket を用いたリアルタイム同期
- 生成 AI を利用した出題補助機能（設定時）

---

## ゲームの流れ

1. ロビーで名前を入力して入場します
2. 自分でルームを作成して出題するか、既存ルームに参加します
3. 参加者は先攻・後攻に分かれて対戦します
4. 問題文の公開、解答、判定、投票などをリアルタイムで進行します
5. 対局終了後は結果や棋譜を確認できます

---

## パスキー認証について

QuizOpenBattle では、パスワードの代わりに **パスキー（WebAuthn）** を用いた認証を採用しています。

### この方式を採用している理由

一般的なパスワード認証では、アプリケーション側でパスワード管理が必要になります。
一方、パスキー方式では端末やブラウザの認証基盤を利用できるため、**アプリ側でパスワードそのものを保存しない**設計にできます。

### このプロジェクトでの認証フロー

本プロジェクトでは、初回登録時に WebAuthn によるパスキー登録を行い、
以後は登録済みのパスキーを使ってログインします。

サーバー側では、登録・認証のたびに次の要素を検証します。

- challenge
- origin
- rp_id
- user verification

これにより、クライアントから返された認証結果をそのまま信用するのではなく、
**サーバー側で正当な WebAuthn 応答かどうかを確認する**構成にしています。

### サーバーに保存する情報

サーバー側に保存するのは、主に以下のような認証情報です。

- credential ID
- 公開鍵
- sign count
- 一部のメタデータ（transport / device type など）

**パスワードそのものは保存しません。**

### セッション管理

パスキー認証に成功すると、サーバーはセッションを発行し、
以後の API 認証には Cookie ベースのセッションを利用します。

このセッション Cookie には、次の属性を設定します。

- `HttpOnly`
- `SameSite=Lax`
- `Secure`（HTTPS 環境）

これにより、JavaScript からの直接参照を避けつつ、
ブラウザ上で比較的安全にセッションを管理できるようにしています。

### WebSocket 接続の保護

ゲーム本体のリアルタイム通信には WebSocket を使っていますが、
接続時には認証済みセッションから発行した **短寿命の署名付き ticket** を利用します。

この ticket は、次の性質を持ちます。

- 有効期限つき
- 署名つき
- nonce による再利用防止
- client_id と紐付け
- 接続時に session / user / client_id の整合性を再確認

そのため、ログイン後のリアルタイム接続についても、
単に WebSocket を開くだけでは接続できないようにしています。

### 安全性についての補足

本プロジェクトは、**安全性を意識した認証設計**を採用しています。
ただし、あらゆるシステムと同様に、安全性は実装だけでなく、HTTPS 配信、環境変数設定、リバースプロキシ構成などの運用条件にも依存します。

そのため、この README では「絶対に安全」とは表現せず、
**どういう保護を採用しているかを明示する**方針をとっています。

---

## ログイン方法

### 初回

1. アカウント名を入力します
2. パスキーを登録します
3. 登録完了後、そのままログイン状態になります

### 2回目以降

1. パスキーでログインします
2. 認証に成功するとセッションが発行されます

### ゲスト参加

アカウントを作成しなくても入場できます。
ただし、一部の機能はログイン時のみ利用できます。

---

## 技術スタック

- Frontend: HTML / CSS / JavaScript
- Backend: Python / FastAPI
- Realtime: WebSocket
- Authentication: WebAuthn / Passkey
- AI-assisted question generation: `<YOUR_AI_PROVIDER_OR_DESCRIPTION>`

---

## ディレクトリ構成

```text
.
├── backend/
├── frontend/
├── README.md
└── <OTHER_DIRECTORIES>
```

---

## セットアップ

### 1. リポジトリを取得

```bash
git clone <YOUR_REPOSITORY_URL>
cd <YOUR_REPOSITORY_DIRECTORY>
```

### 2. 依存関係をインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数を設定

最低限、次の値を環境に合わせて設定してください。

```bash
QUIZ_WEBAUTHN_ORIGIN=<YOUR_HTTPS_ORIGIN>
QUIZ_WEBAUTHN_RP_ID=<YOUR_RP_ID>
QUIZ_WEBAUTHN_RP_NAME=<YOUR_RP_NAME>
QUIZ_WS_AUTH_SECRET=<YOUR_RANDOM_SECRET>
```

必要に応じて、追加の設定も行ってください。

```bash
# 例
QUIZ_COOKIE_SECURE=<0_OR_1>
QUIZ_DIAG_API=<0_OR_1>

# AI 出題機能を使う場合の設定例
<YOUR_AI_ENV_EXAMPLE_1>
<YOUR_AI_ENV_EXAMPLE_2>
```

### 4. サーバーを起動

```bash
<YOUR_START_COMMAND>
```

### 5. ブラウザでアクセス

```text
<YOUR_APP_URL>
```

---

## 開発メモ

* 本番運用では HTTPS 環境を推奨します
* WebAuthn を利用するため、`origin` と `rp_id` の設定は正しく一致させてください
* リバースプロキシ配下で運用する場合は、Cookie の `Secure` 設定や proxy headers の扱いを確認してください
* AI 出題機能を有効にする場合は、別途 API キーやモデル設定が必要です

---

## 既知の注意点

* パスキー認証の利用には、対応ブラウザ・対応端末が必要です
* 認証や Cookie の安全性は、アプリ本体だけでなく配信構成にも依存します
* README のセットアップ例は、利用するホスティング環境に応じて調整が必要な場合があります

---

## 今後の予定

* [ ] README に実際の画面スクリーンショットを追加
* [ ] `RULES.md` を追加してルールを外出し
* [ ] デプロイ手順を Render / ローカル向けに整理
* [ ] ライセンス表記を確定

---

## ライセンス

`<YOUR_LICENSE>`

詳細は [`LICENSE`](./LICENSE) を参照してください。


