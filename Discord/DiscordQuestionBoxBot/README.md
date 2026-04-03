# AnonymousBot

Discord で「Bot へDMすると、Botが特定のテキストチャンネルへ代弁して投稿する」ための Bot です。DMの送信者名はチャンネル側へは表示しません（代弁）。テキストと画像等の添付ファイルの転送に対応しています。

## 機能
- Bot へ送ったDMを、指定されたサーバー内のチャンネルへ代理投稿（テキスト/添付ファイル対応）
- 転送先チャンネルはコマンドで設定可能（`~set`）
- 受信したDMのログを `store.csv` に保存（メッセージID/送信者/本文）

## 動作要件
- Python 3.9（推奨）
- discord.py 1.6.0（`requirements.txt` に記載）

## 事前準備（Discord 開発者ポータル）
1. Discord Bot を作成し、Bot Token を取得。
2. Bot の Privileged Gateway Intents のうち「MESSAGE CONTENT INTENT」を有効化。
3. Bot を対象サーバーへ招待（権限: メッセージの表示/送信、ファイル添付 など）。

## セットアップ
```bash
# 取得
git clone https://github.com/t4t5u0/DiscordQuestionBoxBot.git
cd DiscordQuestionBoxBot

# 依存関係のインストール
pip install -r requirements.txt   # 環境によっては pip3 を使用

# 実行用ディレクトリへ移動
cd discord_qustion_bot

# 設定ファイルの編集（このディレクトリ直下の info.json を使います）
$EDITOR info.json
```

`info.json` の例:
```json
{
  "token": "PASTE_YOUR_DISCORD_BOT_TOKEN",
  "channel_id": 0
}
```
- `token`: 取得した Bot Token を貼り付けてください。
- `channel_id`: 後述のコマンド `~set` で設定する場合は 0 のままでOKです。直接設定する場合は、転送先チャンネルのIDを数値で指定します。

## 起動
```bash
python main.py   # 環境によっては python3
```
バックグラウンド実行例（簡易）:
```bash
nohup python main.py &
```
本番運用では `systemd` 等のプロセス管理ツールの利用を推奨します。

## 転送先チャンネルの設定
起動後、転送したいチャンネル（サーバー内の任意のテキストチャンネル）で次を実行:
```text
~set
```
このチャンネルが以後の転送先として `info.json` に保存されます。

直接 `info.json` にチャンネルIDを書いて起動することも可能です。

チャンネルIDの取得方法（例）:
- Discord クライアントの「開発者モード」を有効化 → チャンネルを右クリック → 「IDをコピー」

## 使い方
1. ユーザーが Bot へDMでテキストや画像を送る
2. Bot が設定済みのチャンネルへ代弁して投稿
   - テキストはそのまま投稿
   - 添付ファイルも取得して再投稿

DMの内容は `store.csv` にも追記されます（メッセージID/送信者タグ/本文）。匿名での可視化が目的ですが、運用監査のために送信者はローカルに記録される点に注意してください。

## コマンド
- `~help`: ヘルプ表示
- `~set`: 実行したチャンネルを転送先に設定

## 注意事項
- 実行パスに依存する相対パス（`./info.json`, `./store.csv`）を利用しています。必ず `discord_qustion_bot` ディレクトリで起動してください。
- 既定ではDM以外（サーバー内の通常チャンネル）からのメッセージには反応しません。
- 依存する `discord.py==1.6.0` の仕様に依存します。新しいバージョンへ更新する場合はコード側の修正が必要になる場合があります。

## ライセンス
MIT（元リポジトリのライセンスに準拠）
