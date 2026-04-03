import discord
from discord.ext import commands
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from dotenv import load_dotenv
import os
import json
import uuid
import math
from typing import Dict, Any

# ----------------------------
# 設定
# ----------------------------
DATA_FILE = "reservations.json"
PAGE_SIZE = 5  # /list の1ページあたりの件数（必要に応じて変更）
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler()

# in-memory reservations structure:
# reservations: Dict[str(guild_id)] = {
#    rid: {
#       "id": rid,
#       "date": "YYYY-MM-DD",
#       "time": "HH:MM",
#       "message": "...",
#       "channel": channel_id,
#       "author": author_id,
#       "job": <apscheduler job>  # not saved to file
#    }, ...
# }
reservations: Dict[str, Dict[str, Dict[str, Any]]] = {}

# ----------------------------
# ファイル読み書き（堅牢に）
# ----------------------------
def load_from_file() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                # 想定外の形式なら空にする
                return {}
            # 更に型チェック：各 guild value は dict であること
            sanitized: Dict[str, Dict[str, Any]] = {}
            for gk, gv in data.items():
                if isinstance(gv, dict):
                    # ensure inner mapping reservation_id -> dict
                    inner: Dict[str, Dict[str, Any]] = {}
                    for rid, info in gv.items():
                        if isinstance(info, dict) and "date" in info and "time" in info and "message" in info and "channel" in info:
                            inner[rid] = info
                        else:
                            # skip malformed entry
                            continue
                    if inner:
                        sanitized[gk] = inner
                # else skip malformed guild entry
            return sanitized
    except Exception as e:
        print(f"[WARN] reservations.json 読込エラー: {e}")
        return {}

def save_to_file():
    try:
        to_save: Dict[str, Dict[str, Any]] = {}
        for gid, guild_map in reservations.items():
            to_save[gid] = {}
            for rid, info in guild_map.items():
                # copy only serializable fields (exclude job)
                to_save[gid][rid] = {
                    "id": info.get("id"),
                    "date": info.get("date"),
                    "time": info.get("time"),
                    "message": info.get("message"),
                    "channel": info.get("channel"),
                    "author": info.get("author")
                }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] reservations.json 保存エラー: {e}")

# ----------------------------
# 日時ユーティリティ
# ----------------------------
def parse_dt(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

def dt_from_info(info: Dict[str, Any]) -> datetime:
    return parse_dt(info["date"], info["time"])

def dt_to_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")

# ----------------------------
# メッセージ送信（ジョブから呼ばれる）
# ----------------------------
async def send_reserved_message(channel_id: int, message_text: str):
    channel = bot.get_channel(channel_id)
    if channel:
        # @everyone をそのまま機能させる（roles/users 有効にしました※20251126）
        allowed = discord.AllowedMentions(everyone=True, users=True, roles=True)
        try:
            await channel.send(message_text, allowed_mentions=allowed)
        except Exception as e:
            print(f"[ERROR] 予約メッセージ送信失敗: {e}")
    else:
        print(f"[WARN] チャンネル {channel_id} が見つかりません。")

# ----------------------------
# スケジュール登録
# ----------------------------
def schedule_job_for(rid: str, info: Dict[str, Any]):
    """info は reservations[guild_id][rid] の辞書（job フィールドは無い又は None）"""
    try:
        send_time = dt_from_info(info)
    except Exception:
        return None

    # capture channel and message now
    channel_id = info["channel"]
    message_text = info["message"]

    job = scheduler.add_job(
        lambda ch=channel_id, msg=message_text: bot.loop.create_task(send_reserved_message(ch, msg)),
        "date",
        run_date=send_time
    )
    return job

# ----------------------------
# 起動時の復元処理（ファイル -> メモリ -> ジョブ）
# ----------------------------
def restore_on_startup():
    global reservations
    raw = load_from_file()
    reservations = {}  # reset memory
    now = datetime.now()
    restored = 0
    removed = 0
    for gid, guild_map in raw.items():
        # prepare empty guild map
        for rid, info in guild_map.items():
            # validate fields
            try:
                send_time = dt_from_info(info)
            except Exception:
                # skip malformed entry
                continue
            if send_time <= now:
                removed += 1
                continue
            # ensure guild exist
            if gid not in reservations:
                reservations[gid] = {}
            # copy and leave job None for now
            reservations[gid][rid] = {
                "id": rid,
                "date": info["date"],
                "time": info["time"],
                "message": info["message"],
                "channel": info["channel"],
                "author": info.get("author"),
                "job": None
            }
            restored += 1

    # save cleaned data (remove past/malformed)
    save_to_file()

    # schedule jobs for restored entries
    for gid, guild_map in reservations.items():
        for rid, info in guild_map.items():
            try:
                job = schedule_job_for(rid, info)
                if job:
                    reservations[gid][rid]["job"] = job
            except Exception as e:
                print(f"[WARN] ジョブ登録失敗: {e}")

    print(f"[INFO] 復元: {restored} 件, 過去削除: {removed} 件")

# ----------------------------
# 過去予約の自動削除（操作時に呼ぶ）
# ----------------------------
def cleanup_past_for_guild(guild_id: str):
    changed = False
    now = datetime.now()
    if guild_id not in reservations:
        return
    for rid, info in list(reservations[guild_id].items()):
        try:
            send_time = dt_from_info(info)
        except Exception:
            # malformed -> remove
            del reservations[guild_id][rid]
            changed = True
            continue
        if send_time <= now:
            # remove scheduled job if exists
            job = info.get("job")
            if job:
                try:
                    job.remove()
                except Exception:
                    pass
            del reservations[guild_id][rid]
            changed = True
    if changed:
        save_to_file()

# ----------------------------
# on_ready
# ----------------------------
@bot.event
async def on_ready():
    print(f"ログイン成功: {bot.user}")
    # restore from file (clean & schedule)
    restore_on_startup()
    # start scheduler
    scheduler.start()
    # sync commands
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを同期しました: {len(synced)} 件")
    except Exception as e:
        print(f"[WARN] スラッシュコマンド同期失敗: {e}")

# ----------------------------
# Reserve Modal
# ----------------------------
class ReserveModal(discord.ui.Modal, title="メッセージ予約"):
    date = discord.ui.TextInput(label="日付 (YYYY-MM-DD)", placeholder="2025-09-21", max_length=10)
    time = discord.ui.TextInput(label="時刻 (HH:MM)", placeholder="21:00", max_length=5)
    message = discord.ui.TextInput(
        label="メッセージ（複数行可）",
        style=discord.TextStyle.paragraph,
        placeholder="ここにメッセージを入力。@everyone は有効",
        max_length=2000
    )

    def __init__(self, original_interaction: discord.Interaction):
        super().__init__()
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        # operate only for the modal opener context
        guild_id = str(self.original_interaction.guild_id)
        channel = self.original_interaction.channel
        author = self.original_interaction.user

        # cleanup past
        cleanup_past_for_guild(guild_id)

        # validate datetime
        try:
            send_time = parse_dt(self.date.value.strip(), self.time.value.strip())
        except Exception:
            await interaction.response.send_message("日付または時刻の形式が不正です。YYYY-MM-DD / HH:MM で入力してください。", ephemeral=True)
            return

        if send_time <= datetime.now():
            await interaction.response.send_message("過去の時間は予約できません。", ephemeral=True)
            return

        # prepare reservation entry
        rid = str(uuid.uuid4())[:8]
        info = {
            "id": rid,
            "date": self.date.value.strip(),
            "time": self.time.value.strip(),
            "message": self.message.value,
            "channel": channel.id,
            "author": author.id,
            "job": None
        }

        # ensure guild map exists
        if guild_id not in reservations:
            reservations[guild_id] = {}

        # save to memory & schedule
        reservations[guild_id][rid] = info
        job = schedule_job_for(rid, info)
        if job:
            reservations[guild_id][rid]["job"] = job

        save_to_file()

        await interaction.response.send_message(f"予約しました！\nID: `{rid}`\n日時: {info['date']} {info['time']}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[ERROR] Modal error: {error}")
        try:
            await interaction.response.send_message("予約中にエラーが発生しました。", ephemeral=True)
        except Exception:
            pass

# ----------------------------
# /reserve コマンド (Modalを開く)
# ----------------------------
@bot.tree.command(name="reserve", description="メッセージを予約します（フォームが開きます）")
async def reserve_cmd(interaction: discord.Interaction):
    modal = ReserveModal(interaction)
    await interaction.response.send_modal(modal)

# ----------------------------
# /list コマンド（Embed + ページネーション）
# ----------------------------
class ListView(discord.ui.View):
    def __init__(self, user_id: int, embeds: list):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.embeds = embeds
        self.current = 0
        # create buttons and attach callbacks
        self.prev_btn = discord.ui.Button(label="◀ 前へ", style=discord.ButtonStyle.primary)
        self.next_btn = discord.ui.Button(label="次へ ▶", style=discord.ButtonStyle.primary)
        self.prev_btn.callback = self.prev_cb
        self.next_btn.callback = self.next_cb
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.current == 0)
        self.next_btn.disabled = (self.current >= len(self.embeds) - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この操作はコマンド実行者のみ利用できます。", ephemeral=True)
            return False
        return True

    async def prev_cb(self, interaction: discord.Interaction):
        if self.current > 0:
            self.current -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def next_cb(self, interaction: discord.Interaction):
        if self.current < len(self.embeds) - 1:
            self.current += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

@bot.tree.command(name="list", description="このサーバーの予約一覧を表示します")
async def list_cmd(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    cleanup_past_for_guild(guild_id)

    if guild_id not in reservations or not reservations[guild_id]:
        return await interaction.response.send_message("現在、予約はありません。", ephemeral=True)

    # sort by datetime
    items = sorted(reservations[guild_id].values(), key=lambda x: dt_from_info(x))

    # prepare embeds pages
    total = len(items)
    total_pages = math.ceil(total / PAGE_SIZE)
    embeds = []
    for p in range(total_pages):
        chunk = items[p * PAGE_SIZE:(p + 1) * PAGE_SIZE]
        emb = discord.Embed(title=f"予約一覧 (ページ {p+1}/{total_pages})", color=0x2ecc71)
        for entry in chunk:
            rid = entry["id"]
            dt = f"{entry['date']} {entry['time']}"
            channel_mention = f"<#{entry['channel']}>"
            preview = entry["message"]
            if len(preview) > 400:
                preview = preview[:397] + "..."
            emb.add_field(name=f"ID: {rid} | {dt}", value=f"{channel_mention}\n{preview}", inline=False)
        embeds.append(emb)

    view = ListView(interaction.user.id, embeds)
    await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)

# ----------------------------
# /cancel コマンド
# ----------------------------
@bot.tree.command(name="cancel", description="指定したIDの予約を取り消します")
@app_commands.describe(reservation_id="キャンセルする予約ID")
async def cancel_cmd(interaction: discord.Interaction, reservation_id: str):
    guild_id = str(interaction.guild_id)
    cleanup_past_for_guild(guild_id)

    if guild_id not in reservations or reservation_id not in reservations[guild_id]:
        return await interaction.response.send_message("指定された予約 ID は存在しません。", ephemeral=True)

    # remove job if exists
    job = reservations[guild_id][reservation_id].get("job")
    if job:
        try:
            job.remove()
        except Exception:
            pass

    del reservations[guild_id][reservation_id]
    save_to_file()
    await interaction.response.send_message(f"予約 {reservation_id} をキャンセルしました。", ephemeral=True)

# ----------------------------
# shutdown (owner only)
# ----------------------------
@bot.tree.command(name="shutdown", description="Bot を安全に停止します（所有者のみ）")
async def shutdown_cmd(interaction: discord.Interaction):
    owner = await bot.application_info()
    if interaction.user.id != owner.owner.id:
        return await interaction.response.send_message("あなたは実行できません。", ephemeral=True)
    await interaction.response.send_message("Bot を停止します...", ephemeral=True)
    await bot.close()

# ----------------------------
# 実行用: 起動前準備
# ----------------------------
if __name__ == "__main__":
    # データファイルがない or 中身が不正なら空オブジェクト作成
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

    bot.run(TOKEN)
