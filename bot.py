import discord
from discord.ext import commands
import json
import os
import time
import asyncio
import re
import datetime
from collections import defaultdict

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

config = load_config()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

spam_tracker   = defaultdict(list)
mention_tracker = defaultdict(list)
link_tracker   = defaultdict(list)

LINK_REGEX = re.compile(r"https?://|discord\.gg/|www\.", re.IGNORECASE)

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def guild_config(guild_id):
    key = str(guild_id)
    if key not in config:
        config[key] = {}
    return config[key]

def e_ok(title, desc):
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ecc71)

def e_err(desc):
    return discord.Embed(title="❌ Erreur", description=desc, color=0xe74c3c)

def e_info(title, desc):
    return discord.Embed(title=f"ℹ️ {title}", description=desc, color=0x3498db)

async def do_timeout(member, seconds, reason):
    try:
        until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        return True
    except Exception:
        return False

# ─────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name="!help"))

@bot.event
async def on_member_join(member):
    cfg = guild_config(member.guild.id)

    if cfg.get("welcome_channel"):
        ch = member.guild.get_channel(cfg["welcome_channel"])
        if ch:
            msg = cfg.get("welcome_message", "Bienvenue {mention} sur **{server}** ! 🎉")
            msg = msg.replace("{mention}", member.mention)\
                     .replace("{name}", member.name)\
                     .replace("{server}", member.guild.name)\
                     .replace("{count}", str(member.guild.member_count))
            embed = discord.Embed(description=msg, color=0x9b59b6)
            embed.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=embed)

    if cfg.get("welcome_dm"):
        dm_msg = cfg.get("welcome_dm_message", "Bienvenue sur **{server}** ! 🎉")
        dm_msg = dm_msg.replace("{mention}", member.mention)\
                       .replace("{name}", member.name)\
                       .replace("{server}", member.guild.name)\
                       .replace("{count}", str(member.guild.member_count))
        try:
            e = discord.Embed(description=dm_msg, color=0x9b59b6)
            await member.send(embed=e)
        except discord.Forbidden:
            pass

    if cfg.get("auto_role"):
        role = member.guild.get_role(cfg["auto_role"])
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if not message.guild:
        return

    cfg = guild_config(message.guild.id)
    member = message.author

    # ── Image only ──
    if message.channel.id in cfg.get("image_only_channels", []):
        has_img = any(a.content_type and a.content_type.startswith("image") for a in message.attachments)
        if not has_img:
            try:
                await message.delete()
                w = await message.channel.send(f"{member.mention} ❌ Ce salon accepte **uniquement des images** !")
                await w.delete(delay=5)
            except discord.Forbidden:
                pass
            return

    now = time.time()

    # ── Anti-spam (messages) ──
    if cfg.get("antispam_enabled"):
        limit = cfg.get("antispam_limit", 5)
        secs  = cfg.get("antispam_seconds", 5)
        uid = member.id
        spam_tracker[uid] = [t for t in spam_tracker[uid] if now - t < secs]
        spam_tracker[uid].append(now)
        if len(spam_tracker[uid]) >= limit:
            spam_tracker[uid] = []
            timeout_dur = cfg.get("antispam_timeout", 60)
            try:
                await message.delete()
            except Exception:
                pass
            await do_timeout(member, timeout_dur, "Anti-spam : trop de messages")
            w = await message.channel.send(
                f"{member.mention} ⛔ **Anti-spam** : trop de messages ! Timeout **{timeout_dur}s**.")
            await w.delete(delay=8)
            return

    # ── Anti-mention ──
    if cfg.get("antimention_enabled") and message.mentions:
        limit = cfg.get("antimention_limit", 3)
        secs  = cfg.get("antimention_seconds", 10)
        uid = member.id
        mention_tracker[uid] = [t for t in mention_tracker[uid] if now - t < secs]
        mention_tracker[uid].extend([now] * len(message.mentions))
        if len(mention_tracker[uid]) >= limit:
            mention_tracker[uid] = []
            timeout_dur = cfg.get("antimention_timeout", 60)
            try:
                await message.delete()
            except Exception:
                pass
            await do_timeout(member, timeout_dur, "Anti-mention : trop de mentions")
            w = await message.channel.send(
                f"{member.mention} ⛔ **Anti-mention** : trop de mentions ! Timeout **{timeout_dur}s**.")
            await w.delete(delay=8)
            return

    # ── Anti-link ──
    if cfg.get("antilink_enabled") and LINK_REGEX.search(message.content):
        limit = cfg.get("antilink_limit", 2)
        secs  = cfg.get("antilink_seconds", 10)
        uid = member.id
        link_tracker[uid] = [t for t in link_tracker[uid] if now - t < secs]
        link_tracker[uid].append(now)
        if len(link_tracker[uid]) >= limit:
            link_tracker[uid] = []
            timeout_dur = cfg.get("antilink_timeout", 60)
            try:
                await message.delete()
            except Exception:
                pass
            await do_timeout(member, timeout_dur, "Anti-link : trop de liens")
            w = await message.channel.send(
                f"{member.mention} ⛔ **Anti-link** : trop de liens ! Timeout **{timeout_dur}s**.")
            await w.delete(delay=8)
            return
        else:
            # Supprimer le lien même sans timeout si activé et 1 lien envoyé
            try:
                await message.delete()
                w = await message.channel.send(f"{member.mention} ❌ Les liens sont interdits ici !")
                await w.delete(delay=5)
            except Exception:
                pass
            return

    await bot.process_commands(message)

# ─────────────────────────────────────────
#  VIEWS — Boutons !join
# ─────────────────────────────────────────

class JoinView(discord.ui.View):
    def __init__(self, cfg, guild, author):
        super().__init__(timeout=300)
        self.cfg = cfg
        self.guild = guild
        self.author = author

    def check(self, interaction):
        return interaction.user.id == self.author.id

    # ── Bienvenue ──
    @discord.ui.button(label="📢 Salon bienvenue", style=discord.ButtonStyle.primary, row=0)
    async def btn_welcome_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Mentionne le **salon de bienvenue** (ex: #bienvenue) ou tape `disable` :", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        if msg.content.lower() == "disable":
            self.cfg.pop("welcome_channel", None)
        elif msg.channel_mentions:
            self.cfg["welcome_channel"] = msg.channel_mentions[0].id
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Salon mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    @discord.ui.button(label="💬 Message salon", style=discord.ButtonStyle.primary, row=0)
    async def btn_welcome_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Envoie le **message de bienvenue** (variables: `{mention}` `{name}` `{server}` `{count}`) :", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        self.cfg["welcome_message"] = msg.content
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Message mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    @discord.ui.button(label="📩 Message MP", style=discord.ButtonStyle.primary, row=0)
    async def btn_welcome_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Envoie le **message MP** à envoyer au nouveau membre, ou `disable` pour désactiver :", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        if msg.content.lower() == "disable":
            self.cfg["welcome_dm"] = False
            self.cfg.pop("welcome_dm_message", None)
        else:
            self.cfg["welcome_dm"] = True
            self.cfg["welcome_dm_message"] = msg.content
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("MP mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    @discord.ui.button(label="🎭 Rôle auto", style=discord.ButtonStyle.primary, row=0)
    async def btn_auto_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Mentionne le **rôle automatique** (ex: @Membre) ou tape `disable` :", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        if msg.content.lower() == "disable":
            self.cfg.pop("auto_role", None)
        elif msg.role_mentions:
            self.cfg["auto_role"] = msg.role_mentions[0].id
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Rôle mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    # ── Anti-spam ──
    @discord.ui.button(label="🚫 Anti-spam", style=discord.ButtonStyle.danger, row=1)
    async def btn_antispam(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Configure l'anti-spam :\n"
            "• `on` — activer\n• `off` — désactiver\n"
            "• `set <msgs> <secondes> <timeout_secs>` — ex: `set 5 4 60`", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        parts = msg.content.strip().split()
        if parts[0].lower() == "on":
            self.cfg["antispam_enabled"] = True
        elif parts[0].lower() == "off":
            self.cfg["antispam_enabled"] = False
        elif parts[0].lower() == "set" and len(parts) >= 4:
            try:
                self.cfg["antispam_limit"] = int(parts[1])
                self.cfg["antispam_seconds"] = int(parts[2])
                self.cfg["antispam_timeout"] = int(parts[3])
                self.cfg["antispam_enabled"] = True
            except ValueError:
                pass
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Anti-spam mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    # ── Anti-mention ──
    @discord.ui.button(label="📣 Anti-mention", style=discord.ButtonStyle.danger, row=1)
    async def btn_antimention(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Configure l'anti-mention :\n"
            "• `on` / `off`\n"
            "• `set <mentions> <secondes> <timeout_secs>` — ex: `set 3 10 60`", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        parts = msg.content.strip().split()
        if parts[0].lower() == "on":
            self.cfg["antimention_enabled"] = True
        elif parts[0].lower() == "off":
            self.cfg["antimention_enabled"] = False
        elif parts[0].lower() == "set" and len(parts) >= 4:
            try:
                self.cfg["antimention_limit"] = int(parts[1])
                self.cfg["antimention_seconds"] = int(parts[2])
                self.cfg["antimention_timeout"] = int(parts[3])
                self.cfg["antimention_enabled"] = True
            except ValueError:
                pass
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Anti-mention mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    # ── Anti-link ──
    @discord.ui.button(label="🔗 Anti-link", style=discord.ButtonStyle.danger, row=1)
    async def btn_antilink(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Configure l'anti-link :\n"
            "• `on` / `off`\n"
            "• `set <liens> <secondes> <timeout_secs>` — ex: `set 2 10 60`", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        parts = msg.content.strip().split()
        if parts[0].lower() == "on":
            self.cfg["antilink_enabled"] = True
        elif parts[0].lower() == "off":
            self.cfg["antilink_enabled"] = False
        elif parts[0].lower() == "set" and len(parts) >= 4:
            try:
                self.cfg["antilink_limit"] = int(parts[1])
                self.cfg["antilink_seconds"] = int(parts[2])
                self.cfg["antilink_timeout"] = int(parts[3])
                self.cfg["antilink_enabled"] = True
            except ValueError:
                pass
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Anti-link mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    # ── Image only ──
    @discord.ui.button(label="🖼️ Image only", style=discord.ButtonStyle.secondary, row=2)
    async def btn_imageonly(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.send_message(
            "Gestion des salons image-only :\n"
            "• `add #salon` — restreindre\n"
            "• `remove #salon` — retirer\n"
            "• `clear` — tout retirer", ephemeral=True)
        try:
            msg = await bot.wait_for("message", timeout=60,
                check=lambda m: m.author == self.author and m.channel == interaction.channel)
        except asyncio.TimeoutError:
            return
        parts = msg.content.strip().split()
        if "image_only_channels" not in self.cfg:
            self.cfg["image_only_channels"] = []
        if parts[0].lower() == "add" and msg.channel_mentions:
            cid = msg.channel_mentions[0].id
            if cid not in self.cfg["image_only_channels"]:
                self.cfg["image_only_channels"].append(cid)
        elif parts[0].lower() == "remove" and msg.channel_mentions:
            cid = msg.channel_mentions[0].id
            self.cfg["image_only_channels"] = [c for c in self.cfg["image_only_channels"] if c != cid]
        elif parts[0].lower() == "clear":
            self.cfg["image_only_channels"] = []
        save_config(config)
        await msg.delete()
        await interaction.channel.send(embed=e_ok("Image only mis à jour", ""), delete_after=4)
        await refresh_join_embed(interaction, self.cfg, self.guild, self.author)

    # ── Test bienvenue ──
    @discord.ui.button(label="🧪 Tester bienvenue", style=discord.ButtonStyle.success, row=2)
    async def btn_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.check(interaction):
            return await interaction.response.send_message("❌ Pas ta config !", ephemeral=True)
        await interaction.response.defer()
        await on_member_join(interaction.user)
        await interaction.channel.send(embed=e_ok("Test envoyé !", "Simulation d'arrivée effectuée."), delete_after=5)


async def refresh_join_embed(interaction, cfg, guild, author):
    embed = build_join_embed(cfg, guild)
    view = JoinView(cfg, guild, author)
    await interaction.message.edit(embed=embed, view=view)


def build_join_embed(cfg, guild):
    embed = discord.Embed(
        title="🛠️ Panneau de configuration",
        description="Clique sur un bouton pour modifier un paramètre.\nLes changements sont **sauvegardés immédiatement**.",
        color=0x9b59b6
    )

    # Bienvenue
    wc = cfg.get("welcome_channel")
    wm = cfg.get("welcome_message", "*(par défaut)*")
    embed.add_field(
        name="📢 Salon bienvenue",
        value=f"<#{wc}>" if wc else "❌ Non configuré",
        inline=True
    )
    embed.add_field(
        name="💬 Message salon",
        value=f"```{wm[:80]}```",
        inline=False
    )

    # MP
    dm_on = cfg.get("welcome_dm", False)
    dm_msg = cfg.get("welcome_dm_message", "*(par défaut)*")
    embed.add_field(
        name="📩 Message MP",
        value=f"{'✅ Activé' if dm_on else '❌ Désactivé'}\n```{dm_msg[:60]}```" if dm_on else "❌ Désactivé",
        inline=False
    )

    # Rôle auto
    ar = cfg.get("auto_role")
    role = guild.get_role(ar) if ar else None
    embed.add_field(
        name="🎭 Rôle automatique",
        value=f"@{role.name}" if role else "❌ Non configuré",
        inline=True
    )

    # Image only
    imgs = cfg.get("image_only_channels", [])
    embed.add_field(
        name="🖼️ Salons image only",
        value="\n".join(f"<#{c}>" for c in imgs) if imgs else "*(aucun)*",
        inline=True
    )

    # Anti-spam
    spam_on = cfg.get("antispam_enabled", False)
    spam_l = cfg.get("antispam_limit", 5)
    spam_s = cfg.get("antispam_seconds", 5)
    spam_t = cfg.get("antispam_timeout", 60)
    embed.add_field(
        name="🚫 Anti-spam",
        value=f"{'✅' if spam_on else '❌'} {spam_l} msgs / {spam_s}s → timeout {spam_t}s",
        inline=False
    )

    # Anti-mention
    men_on = cfg.get("antimention_enabled", False)
    men_l = cfg.get("antimention_limit", 3)
    men_s = cfg.get("antimention_seconds", 10)
    men_t = cfg.get("antimention_timeout", 60)
    embed.add_field(
        name="📣 Anti-mention",
        value=f"{'✅' if men_on else '❌'} {men_l} mentions / {men_s}s → timeout {men_t}s",
        inline=False
    )

    # Anti-link
    lnk_on = cfg.get("antilink_enabled", False)
    lnk_l = cfg.get("antilink_limit", 2)
    lnk_s = cfg.get("antilink_seconds", 10)
    lnk_t = cfg.get("antilink_timeout", 60)
    embed.add_field(
        name="🔗 Anti-link",
        value=f"{'✅' if lnk_on else '❌'} {lnk_l} liens / {lnk_s}s → timeout {lnk_t}s",
        inline=False
    )

    embed.set_footer(text="Variables dispo : {mention} {name} {server} {count}  •  Expire dans 5 min")
    return embed

# ─────────────────────────────────────────
#  COMMANDE !join
# ─────────────────────────────────────────

@bot.command(name="join")
@commands.has_permissions(manage_guild=True)
async def join_setup(ctx):
    cfg = guild_config(ctx.guild.id)
    embed = build_join_embed(cfg, ctx.guild)
    view = JoinView(cfg, ctx.guild, ctx.author)
    await ctx.send(embed=embed, view=view)

# ─────────────────────────────────────────
#  COMMANDE !help
# ─────────────────────────────────────────

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Commandes disponibles", color=0x9b59b6)
    embed.add_field(name="🛠️ Config tout-en-un", value="`!join` — Ouvre le **panneau interactif** avec boutons", inline=False)
    embed.add_field(name="🎉 Bienvenue", value=(
        "`!setwelcome #salon`\n`!setwelcomemsg <msg>`\n`!setwelcomedm <msg>`\n`!toggledm`\n`!testwelcome`\n`!disablewelcome`\n"
        "Variables : `{mention}` `{name}` `{server}` `{count}`"
    ), inline=False)
    embed.add_field(name="🎭 Rôle auto", value="`!setautorole @role`\n`!disableautorole`", inline=False)
    embed.add_field(name="🚫 Anti-spam", value="`!antispam on/off`\n`!antispam set <msgs> <secs> <timeout>`", inline=False)
    embed.add_field(name="📣 Anti-mention", value="`!antimention on/off`\n`!antimention set <mentions> <secs> <timeout>`", inline=False)
    embed.add_field(name="🔗 Anti-link", value="`!antilink on/off`\n`!antilink set <liens> <secs> <timeout>`", inline=False)
    embed.add_field(name="🖼️ Image only", value="`!imageonly add #salon`\n`!imageonly remove #salon`\n`!imageonly list`", inline=False)
    embed.add_field(name="⚙️ Autre", value="`!config` — voir toute la config", inline=False)
    embed.set_footer(text="Préfixe : !")
    await ctx.send(embed=embed)

# ─────────────────────────────────────────
#  COMMANDES DIRECTES
# ─────────────────────────────────────────

@bot.command(name="setwelcome")
@commands.has_permissions(manage_guild=True)
async def set_welcome(ctx, channel: discord.TextChannel):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_channel"] = channel.id
    save_config(config)
    await ctx.send(embed=e_ok("Salon configuré", channel.mention))

@bot.command(name="setwelcomemsg")
@commands.has_permissions(manage_guild=True)
async def set_welcome_msg(ctx, *, message: str):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_message"] = message
    save_config(config)
    await ctx.send(embed=e_ok("Message mis à jour", f"> {message}"))

@bot.command(name="setwelcomedm")
@commands.has_permissions(manage_guild=True)
async def set_welcome_dm(ctx, *, message: str):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_dm"] = True
    cfg["welcome_dm_message"] = message
    save_config(config)
    await ctx.send(embed=e_ok("MP configuré", f"> {message}"))

@bot.command(name="toggledm")
@commands.has_permissions(manage_guild=True)
async def toggle_dm(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_dm"] = not cfg.get("welcome_dm", False)
    save_config(config)
    await ctx.send(embed=e_ok("MP bienvenue", f"{'✅ Activé' if cfg['welcome_dm'] else '❌ Désactivé'}"))

@bot.command(name="testwelcome")
@commands.has_permissions(manage_guild=True)
async def test_welcome(ctx):
    await on_member_join(ctx.author)
    await ctx.send(embed=e_ok("Test envoyé !", "Simulation d'arrivée effectuée."))

@bot.command(name="disablewelcome")
@commands.has_permissions(manage_guild=True)
async def disable_welcome(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg.pop("welcome_channel", None)
    cfg["welcome_dm"] = False
    save_config(config)
    await ctx.send(embed=e_ok("Bienvenue désactivée", ""))

@bot.command(name="setautorole")
@commands.has_permissions(manage_roles=True)
async def set_auto_role(ctx, role: discord.Role):
    cfg = guild_config(ctx.guild.id)
    cfg["auto_role"] = role.id
    save_config(config)
    await ctx.send(embed=e_ok("Rôle auto", f"**{role.name}** donné à chaque arrivée."))

@bot.command(name="disableautorole")
@commands.has_permissions(manage_roles=True)
async def disable_auto_role(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg.pop("auto_role", None)
    save_config(config)
    await ctx.send(embed=e_ok("Rôle auto désactivé", ""))

# Antispam direct
@bot.command(name="antispam")
@commands.has_permissions(manage_guild=True)
async def antispam_cmd(ctx, action: str, *args):
    cfg = guild_config(ctx.guild.id)
    if action == "on":
        cfg["antispam_enabled"] = True
    elif action == "off":
        cfg["antispam_enabled"] = False
    elif action == "set" and len(args) >= 3:
        cfg["antispam_limit"], cfg["antispam_seconds"], cfg["antispam_timeout"] = int(args[0]), int(args[1]), int(args[2])
        cfg["antispam_enabled"] = True
    save_config(config)
    await ctx.send(embed=e_ok("Anti-spam", f"Statut : {'✅' if cfg.get('antispam_enabled') else '❌'}"))

# Antimention direct
@bot.command(name="antimention")
@commands.has_permissions(manage_guild=True)
async def antimention_cmd(ctx, action: str, *args):
    cfg = guild_config(ctx.guild.id)
    if action == "on":
        cfg["antimention_enabled"] = True
    elif action == "off":
        cfg["antimention_enabled"] = False
    elif action == "set" and len(args) >= 3:
        cfg["antimention_limit"], cfg["antimention_seconds"], cfg["antimention_timeout"] = int(args[0]), int(args[1]), int(args[2])
        cfg["antimention_enabled"] = True
    save_config(config)
    await ctx.send(embed=e_ok("Anti-mention", f"Statut : {'✅' if cfg.get('antimention_enabled') else '❌'}"))

# Antilink direct
@bot.command(name="antilink")
@commands.has_permissions(manage_guild=True)
async def antilink_cmd(ctx, action: str, *args):
    cfg = guild_config(ctx.guild.id)
    if action == "on":
        cfg["antilink_enabled"] = True
    elif action == "off":
        cfg["antilink_enabled"] = False
    elif action == "set" and len(args) >= 3:
        cfg["antilink_limit"], cfg["antilink_seconds"], cfg["antilink_timeout"] = int(args[0]), int(args[1]), int(args[2])
        cfg["antilink_enabled"] = True
    save_config(config)
    await ctx.send(embed=e_ok("Anti-link", f"Statut : {'✅' if cfg.get('antilink_enabled') else '❌'}"))

@bot.command(name="imageonly")
@commands.has_permissions(manage_channels=True)
async def image_only(ctx, action: str, channel: discord.TextChannel = None):
    cfg = guild_config(ctx.guild.id)
    if "image_only_channels" not in cfg:
        cfg["image_only_channels"] = []
    if action == "add" and channel:
        if channel.id not in cfg["image_only_channels"]:
            cfg["image_only_channels"].append(channel.id)
        save_config(config)
        await ctx.send(embed=e_ok("Ajouté", channel.mention))
    elif action == "remove" and channel:
        cfg["image_only_channels"] = [c for c in cfg["image_only_channels"] if c != channel.id]
        save_config(config)
        await ctx.send(embed=e_ok("Retiré", channel.mention))
    elif action == "list":
        lst = cfg.get("image_only_channels", [])
        await ctx.send(embed=e_info("Image only", "\n".join(f"<#{c}>" for c in lst) or "*(aucun)*"))

@bot.command(name="config")
@commands.has_permissions(manage_guild=True)
async def show_config(ctx):
    cfg = guild_config(ctx.guild.id)
    embed = build_join_embed(cfg, ctx.guild)
    embed.title = "⚙️ Configuration actuelle"
    embed.description = "Utilise `!join` pour modifier avec les boutons."
    await ctx.send(embed=embed)

# ─────────────────────────────────────────
#  ERREURS
# ─────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=e_err("Permission refusée."))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=e_err("Argument manquant. Tape `!help`"))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=e_err("Argument invalide. Tape `!help`"))
    elif isinstance(error, commands.CommandNotFound):
        pass

# ─────────────────────────────────────────
#  LANCEMENT
# ─────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERREUR : Variable DISCORD_TOKEN manquante !")
    exit(1)

bot.run(TOKEN)
