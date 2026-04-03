import discord
from discord.ext import commands
import json

# --- 設定読み込み ---
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["token"]
lobbies = config["lobbies"]
accessible_roles = config["accessible_roles"]

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- 管理用辞書 ---
active_vcs = {}  # {owner_id: voice_channel}
linked_text_channels = {}  # {vc_id: {"text": text_channel, "owner": user_id}}

# --- UIコンポーネント ---
class VCSettingsModal(discord.ui.Modal, title="VC設定変更"):
    name = discord.ui.TextInput(label="VCの新しい名前", required=False, max_length=50)
    user_limit = discord.ui.TextInput(label="最大人数（0で制限なし）", required=False, max_length=3)

    def __init__(self, vc: discord.VoiceChannel, owner: discord.Member):
        super().__init__()
        self.vc = vc
        self.owner = owner

    async def on_submit(self, interaction: discord.Interaction):
        # 所有者チェック
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("⚠️ あなたには設定変更の権限がありません。", ephemeral=True)
            return

        try:
            if self.name.value:
                await self.vc.edit(name=self.name.value)
            if self.user_limit.value.isdigit():
                limit = int(self.user_limit.value)
                await self.vc.edit(user_limit=limit)
            await interaction.response.send_message("✅ 設定を更新しました。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ エラー: {e}", ephemeral=True)

class VCSettingsView(discord.ui.View):
    def __init__(self, vc: discord.VoiceChannel, owner: discord.Member):
        super().__init__(timeout=None)
        self.vc = vc
        self.owner = owner

    @discord.ui.button(label="設定変更", style=discord.ButtonStyle.primary)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 所有者以外は押せない
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("⚠️ このVCの設定を変更できるのは作成者（または権限譲渡を受けた人）のみです。", ephemeral=True)
            return

        await interaction.response.send_modal(VCSettingsModal(self.vc, self.owner))

# --- イベントハンドラ ---
@bot.event
async def on_voice_state_update(member, before, after):
    # --- ユーザーがVCに入ったとき ---
    if after.channel:
        for mode, data in lobbies.items():
            if str(after.channel.id) == data["channel_id"]:
                category = member.guild.get_channel(int(data["category_id"]))
                max_members = data["max_members"]

                vc_name = "個通中" if max_members == 2 else f"{member.display_name}の部屋"
                new_vc = await category.create_voice_channel(
                    name=vc_name,
                    user_limit=max_members if max_members > 0 else 0
                )

                # 権限設定（基本は全員非表示）
                overwrites = {
                    member.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    member: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
                    bot.user: discord.PermissionOverwrite(view_channel=True, connect=True),
                }

                # アクセス許可ロール（あくまでVC入室可）
                for role_id in accessible_roles:
                    role = member.guild.get_role(int(role_id))
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(view_channel=True)

                await new_vc.edit(overwrites=overwrites)
                await member.move_to(new_vc)
                active_vcs[member.id] = new_vc

                # --- 無制限部屋なら設定チャンネル生成 ---
                if max_members == 0:
                    text_channel = await category.create_text_channel(
                        name=f"{member.display_name}-設定",
                        overwrites={
                            member.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                            member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                            bot.user: discord.PermissionOverwrite(view_channel=True)
                        }
                    )

                    linked_text_channels[new_vc.id] = {"text": text_channel, "owner": member.id}
                    await text_channel.send(
                        f"{member.mention} のVC設定はこちら👇",
                        view=VCSettingsView(new_vc, member)
                    )

                break

    # --- ユーザーがVCを抜けたとき ---
    if before.channel and before.channel.id not in [
        int(lobbies["2person"]["channel_id"]),
        int(lobbies["unlimited"]["channel_id"])
    ]:
        # --- 無制限部屋の設定チャンネルが紐づいている場合 ---
        if before.channel.id in linked_text_channels:
            data = linked_text_channels[before.channel.id]
            text_channel = data["text"]
            owner_id = data["owner"]
            remaining = before.channel.members

            # --- 全員抜けた場合 → 削除 ---
            if len(remaining) == 0:
                await before.channel.delete()
                await text_channel.delete()
                linked_text_channels.pop(before.channel.id, None)
                active_vcs.pop(owner_id, None)
                return

            # --- オーナーが抜けた場合のみ譲渡 ---
            if member.id == owner_id:
                new_owner = remaining[0]

                # 権限譲渡：新オーナーに閲覧・送信許可
                await text_channel.set_permissions(new_owner, view_channel=True, send_messages=True)
                await text_channel.set_permissions(member, overwrite=None)

                # オーナー情報更新
                linked_text_channels[before.channel.id]["owner"] = new_owner.id

                # 設定メッセージを再投稿（新しいボタン付き）
                await text_channel.send(
                    f"👑 {new_owner.mention} に管理権限が譲渡されました。",
                    view=VCSettingsView(before.channel, new_owner)
                )

                print(f"👑 {new_owner.display_name} に管理権限を譲渡しました。")

        # --- 2人部屋（空なら削除） ---
        elif len(before.channel.members) == 0:
            await before.channel.delete()
            for uid, vc in list(active_vcs.items()):
                if vc.id == before.channel.id:
                    active_vcs.pop(uid, None)

@bot.event
async def on_ready():
    print(f"✅ ログイン成功: {bot.user}")

bot.run(TOKEN)
