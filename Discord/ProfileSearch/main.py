import discord
from discord import app_commands
from discord.ext import commands
import json
import re

# ======== 設定ファイル =========
with open("info.json", "r", encoding="utf-8") as f:
    INFO = json.load(f)

TOKEN = INFO["token"]
FEMALE_CHANNEL_ID = INFO["female_channel_id"]
MALE_CHANNEL_ID = INFO["male_channel_id"]
COUPLE_CHANNEL_ID = INFO["couple_channel_id"]

INTRO_CHANNELS = {
    "女性": FEMALE_CHANNEL_ID,
    "男性": MALE_CHANNEL_ID,
    "カップル": COUPLE_CHANNEL_ID
}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

PROFILE_FILE = "profiles.json"

# ======== データ管理 =========
def save_profiles(profiles):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)

def load_profiles():
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

# ======== 自己紹介取得 =========
async def fetch_profiles():
    profiles = []
    for category, channel_id in INTRO_CHANNELS.items():
        channel = bot.get_channel(channel_id)
        if channel is None:
            continue
        async for msg in channel.history(limit=None):
            if msg.author.bot:
                continue
            profiles.append({
                "user_id": msg.author.id,
                "name": msg.author.display_name,
                "content": msg.content,
                "category": category,
                "message_link": msg.jump_url
            })
    save_profiles(profiles)
    print(f"[INFO] {len(profiles)} 件のプロフィールを読み込みました。")

# ======== 年齢曖昧マッチ =========
def age_match(content, query):
    if not query:
        return True
    query = query.strip()
    if re.match(r"\d+", query):
        return query in content
    patterns = {
        "10代": r"1\d",
        "20代": r"2\d",
        "30代": r"3\d",
        "40代": r"4\d",
        "20代前半": r"2[0-4]",
        "20代後半": r"2[5-9]",
        "30前半": r"3[0-4]",
        "30後半": r"3[5-9]",
    }
    for k, v in patterns.items():
        if k in query and re.search(v, content):
            return True
    return False

# ======== 検索ロジック =========
def search_profiles(name, age, region):
    profiles = load_profiles()
    results = []
    for p in profiles:
        text = p["content"]
        if name and name not in text:
            continue
        if region and region not in text:
            continue
        if age and not age_match(text, age):
            continue
        results.append(p)
    return results

# ======== 選択メニュー用View =========
class ProfileSelectView(discord.ui.View):
    def __init__(self, profiles):
        super().__init__(timeout=60)  # 60秒でタイムアウト
        options = []
        for p in profiles[:25]:  # Discord dropdown は最大25件
            label = f"{p['name']} ({p['category']})"
            options.append(discord.SelectOption(label=label, value=str(p['user_id'])))
        self.select = discord.ui.Select(placeholder="プロフィールを選択してください", options=options)
        self.select.callback = self.callback
        self.add_item(self.select)
        self.profiles = profiles

    async def callback(self, interaction: discord.Interaction):
        user_id = int(self.select.values[0])
        p = next((p for p in self.profiles if p["user_id"] == user_id), None)
        if p is None:
            await interaction.response.send_message("選択したプロフィールが見つかりませんでした。", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"{p['name']} さんのプロフィール ({p['category']})",
            description=p["content"][:1024],
            color=discord.Color.blurple()
        )
        embed.add_field(name="メッセージリンク", value=f"[ジャンプ]({p['message_link']})", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

# ======== モーダル =========
class SearchModal(discord.ui.Modal, title="プロフィール検索"):
    name_input = discord.ui.TextInput(label="名前（任意）", required=False, placeholder="例：ゆり")
    age_input = discord.ui.TextInput(label="年齢（任意）", required=False, placeholder="例：25, 20代後半, 30前半など")
    region_input = discord.ui.TextInput(label="地域（任意）", required=False, placeholder="例：東京")

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        age = self.age_input.value.strip()
        region = self.region_input.value.strip()

        results = search_profiles(name, age, region)

        if not results:
            await interaction.response.send_message("該当する自己紹介は見つかりませんでした。", ephemeral=True)
            return

        if len(results) == 1:
            p = results[0]
            embed = discord.Embed(
                title=f"{p['name']} さんのプロフィール ({p['category']})",
                description=p["content"][:1024],
                color=discord.Color.blurple()
            )
            embed.add_field(name="メッセージリンク", value=f"[ジャンプ]({p['message_link']})", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=False)
        else:
            view = ProfileSelectView(results)
            await interaction.response.send_message("複数件ヒットしました。選択してください。", view=view, ephemeral=True)

# ======== スラッシュコマンド =========
@bot.tree.command(name="search", description="名前・年齢・地域でプロフィール検索")
async def search_command(interaction: discord.Interaction):
    await interaction.response.send_modal(SearchModal())

# ======== 自己紹介更新イベント =========
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id in INTRO_CHANNELS.values():
        category = next((g for g, cid in INTRO_CHANNELS.items() if cid == message.channel.id), "不明")
        profiles = load_profiles()
        profiles = [p for p in profiles if p["user_id"] != message.author.id]
        profiles.append({
            "user_id": message.author.id,
            "name": message.author.display_name,
            "content": message.content,
            "category": category,
            "message_link": message.jump_url
        })
        save_profiles(profiles)
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
    if after.channel.id not in INTRO_CHANNELS.values():
        return
    profiles = load_profiles()
    for p in profiles:
        if p["user_id"] == after.author.id:
            p["content"] = after.content
    save_profiles(profiles)

@bot.event
async def on_message_delete(message):
    if message.channel.id not in INTRO_CHANNELS.values():
        return
    profiles = load_profiles()
    profiles = [p for p in profiles if p["user_id"] != message.author.id]
    save_profiles(profiles)

# ======== 起動時 =========
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"[BOT起動] {bot.user}")
    await fetch_profiles()

# ======== 手動更新コマンド =========
@bot.tree.command(name="update", description="全プロフィール情報を再取得して更新します")
async def update_profiles(interaction: discord.Interaction):
    await interaction.response.send_message("プロフィールを更新中です。少々お待ちください...", ephemeral=True)
    await fetch_profiles()
    await interaction.followup.send("✅ プロフィールデータを再取得し、更新しました！", ephemeral=False)

# ======== コマンド強制同期 =========
@bot.event
async def on_ready():
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)
        print(f"[SYNC] コマンドを {guild.name} に同期しました。")
    print(f"[BOT起動] {bot.user}")
    await fetch_profiles()

bot.run(TOKEN)
