import discord
from discord import app_commands
from discord.ext import commands
import json
import random

# --- 設定 ---
TOKEN = "TOKEN_ID"

# --- Bot設定 ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- トピック読み込み関数 ---
def load_topics():
    with open("topics.json", "r", encoding="utf-8") as f:
        return json.load(f)

topics = load_topics()


# --- View定義（ボタン表示） ---
class TalkGenreView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="恋愛 💕", style=discord.ButtonStyle.primary)
    async def love_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        topic = random.choice(topics["恋愛"])
        await interaction.response.send_message(f"💘 **恋愛トークテーマ**：{topic}", ephemeral=False)

    @discord.ui.button(label="雑談 💬", style=discord.ButtonStyle.primary)
    async def chat_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        topic = random.choice(topics["雑談"])
        await interaction.response.send_message(f"💬 **雑談トークテーマ**：{topic}", ephemeral=False)

    @discord.ui.button(label="オタク 👓", style=discord.ButtonStyle.primary)
    async def otaku_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        topic = random.choice(topics["オタク"])
        await interaction.response.send_message(f"👓 **オタクトークテーマ**：{topic}", ephemeral=False)


# --- スラッシュコマンド登録 ---
@bot.tree.command(name="talk", description="トークテーマを出すBOT")
async def talk(interaction: discord.Interaction):
    view = TalkGenreView()
    await interaction.response.send_message(
        "話題のジャンルを選んでください！", 
        view=view
    )


# --- 起動時処理 ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ ログイン完了：{bot.user}")


# --- 実行 ---
bot.run(TOKEN)
