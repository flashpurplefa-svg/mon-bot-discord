import discord
from discord.ext import commands
from discord.http import Route
import json, os, time, asyncio, re, datetime, aiohttp
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

spam_tracker    = defaultdict(list)
mention_tracker = defaultdict(list)
link_tracker    = defaultdict(list)

LINK_REGEX = re.compile(r"https?://|discord\.gg/|www\.", re.IGNORECASE)

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def guild_config(guild_id):
    key = str(guild_id)
    if key not in config:
        config[key] = {}
    return config[key]

def e_ok(title, desc=""):
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ecc71)

def e_err(desc):
    return discord.Embed(title="❌ Erreur", description=desc, color=0xe74c3c)

def e_info(title, desc):
    return discord.Embed(title=f"ℹ️ {title}", description=desc, color=0x3498db)

async def do_timeout(member, seconds, reason):
    try:
        until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
    except Exception:
        pass

async def wait_response(bot, author, channel, timeout=60):
    try:
        return await bot.wait_for("message", timeout=timeout,
            check=lambda m: m.author == author and m.channel == channel)
    except asyncio.TimeoutError:
        return None

def parse_emoji_token(token):
    """Convertit un token texte (emoji unicode ou <:nom:id> / <a:nom:id>)
    en quelque chose d'utilisable par message.add_reaction()."""
    token = token.strip()
    if token.startswith("<") and token.endswith(">"):
        try:
            return discord.PartialEmoji.from_str(token)
        except Exception:
            return token
    return token

async def fetch_image_bytes(url):
    """Télécharge une image depuis une URL et retourne ses bytes (ou None en cas d'échec)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception:
        return None

async def get_image_from_ctx(ctx, url):
    """Récupère une image soit depuis une pièce jointe, soit depuis une URL fournie."""
    if ctx.message.attachments:
        return await ctx.message.attachments[0].read()
    if url:
        return await fetch_image_bytes(url)
    return None

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
        dm = cfg.get("welcome_dm_message", "Bienvenue sur **{server}** ! 🎉")
        dm = dm.replace("{mention}", member.mention)\
               .replace("{name}", member.name)\
               .replace("{server}", member.guild.name)\
               .replace("{count}", str(member.guild.member_count))
        try:
            await member.send(embed=discord.Embed(description=dm, color=0x9b59b6))
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
async def on_member_remove(member):
    cfg = guild_config(member.guild.id)

    if cfg.get("leave_channel"):
        ch = member.guild.get_channel(cfg["leave_channel"])
        if ch:
            msg = cfg.get("leave_message", "{name} a quitté **{server}**. 👋")
            msg = msg.replace("{mention}", member.mention)\
                     .replace("{name}", member.name)\
                     .replace("{server}", member.guild.name)\
                     .replace("{count}", str(member.guild.member_count))
            embed = discord.Embed(description=msg, color=0x95a5a6)
            embed.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    cfg = guild_config(message.guild.id)
    member = message.author
    now = time.time()

    # ── Image only ──
    if message.channel.id in cfg.get("image_only_channels", []):
        has_img = any(a.content_type and a.content_type.startswith("image") for a in message.attachments)
        if not has_img:
            try:
                await message.delete()
                w = await message.channel.send(f"{member.mention} ❌ Images uniquement dans ce salon !")
                await w.delete(delay=5)
            except discord.Forbidden:
                pass
            return

    # ── Anti-spam ──
    if cfg.get("antispam_enabled"):
        limit = cfg.get("antispam_limit", 5)
        secs  = cfg.get("antispam_seconds", 5)
        uid   = member.id
        spam_tracker[uid] = [t for t in spam_tracker[uid] if now - t < secs]
        spam_tracker[uid].append(now)
        if len(spam_tracker[uid]) >= limit:
            spam_tracker[uid] = []
            timeout_dur = cfg.get("antispam_timeout", 60)
            try: await message.delete()
            except: pass
            await do_timeout(member, timeout_dur, "Anti-spam")
            w = await message.channel.send(f"{member.mention} ⛔ **Anti-spam** : timeout **{timeout_dur}s** !")
            await w.delete(delay=8)
            return

    # ── Anti-mention ──
    if cfg.get("antimention_enabled") and message.mentions:
        limit = cfg.get("antimention_limit", 3)
        secs  = cfg.get("antimention_seconds", 10)
        uid   = member.id
        mention_tracker[uid] = [t for t in mention_tracker[uid] if now - t < secs]
        mention_tracker[uid].extend([now] * len(message.mentions))
        if len(mention_tracker[uid]) >= limit:
            mention_tracker[uid] = []
            timeout_dur = cfg.get("antimention_timeout", 60)
            try: await message.delete()
            except: pass
            await do_timeout(member, timeout_dur, "Anti-mention")
            w = await message.channel.send(f"{member.mention} ⛔ **Anti-mention** : timeout **{timeout_dur}s** !")
            await w.delete(delay=8)
            return

    # ── Anti-link ──
    if cfg.get("antilink_enabled") and LINK_REGEX.search(message.content):
        limit = cfg.get("antilink_limit", 2)
        secs  = cfg.get("antilink_seconds", 10)
        uid   = member.id
        link_tracker[uid] = [t for t in link_tracker[uid] if now - t < secs]
        link_tracker[uid].append(now)
        try: await message.delete()
        except: pass
        if len(link_tracker[uid]) >= limit:
            link_tracker[uid] = []
            timeout_dur = cfg.get("antilink_timeout", 60)
            await do_timeout(member, timeout_dur, "Anti-link")
            w = await message.channel.send(f"{member.mention} ⛔ **Anti-link** : timeout **{timeout_dur}s** !")
        else:
            w = await message.channel.send(f"{member.mention} ❌ Les liens sont interdits ici !")
        await w.delete(delay=5)
        return

    # ── React Auto ──
    reactauto_cfg = cfg.get("reactauto", {})
    emojis = reactauto_cfg.get(str(message.channel.id))
    if emojis:
        for token in emojis:
            try:
                await message.add_reaction(parse_emoji_token(token))
            except Exception:
                pass

    await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════
#  VIEW : !join  (Bienvenue + Rôle + Image only)
# ═══════════════════════════════════════════════════════════

def build_join_embed(cfg, guild):
    embed = discord.Embed(
        title="🎉 Config — Arrivée des membres",
        description="Clique sur un bouton pour modifier un paramètre.\nChangements sauvegardés **immédiatement**.",
        color=0x9b59b6
    )
    # Salon bienvenue
    wc = cfg.get("welcome_channel")
    embed.add_field(name="📢 Salon bienvenue",
        value=f"<#{wc}>" if wc else "❌ Non configuré", inline=True)

    # Rôle auto
    ar = cfg.get("auto_role")
    role = guild.get_role(ar) if ar else None
    embed.add_field(name="🎭 Rôle automatique",
        value=f"@{role.name}" if role else "❌ Non configuré", inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Message salon
    wm = cfg.get("welcome_message", "*(par défaut)*")
    embed.add_field(name="💬 Message salon",
        value=f"```{wm[:100]}```", inline=False)

    # Message MP
    dm_on = cfg.get("welcome_dm", False)
    dm_msg = cfg.get("welcome_dm_message", "*(par défaut)*")
    embed.add_field(name="📩 Message MP",
        value=f"✅ `{dm_msg[:80]}`" if dm_on else "❌ Désactivé", inline=False)

    # Image only
    imgs = cfg.get("image_only_channels", [])
    embed.add_field(name="🖼️ Salons image only",
        value="\n".join(f"<#{c}>" for c in imgs) if imgs else "*(aucun)*", inline=False)

    embed.set_footer(text="Variables : {mention} {name} {server} {count}  •  Expire dans 5 min")
    return embed


class JoinView(discord.ui.View):
    def __init__(self, cfg, guild, author):
        super().__init__(timeout=300)
        self.cfg    = cfg
        self.guild  = guild
        self.author = author

    def is_author(self, interaction):
        return interaction.user.id == self.author.id

    async def _refresh(self, interaction):
        await interaction.message.edit(
            embed=build_join_embed(self.cfg, self.guild),
            view=JoinView(self.cfg, self.guild, self.author)
        )

    # ── Salon bienvenue ──
    @discord.ui.button(label="📢 Salon bienvenue", style=discord.ButtonStyle.primary, row=0)
    async def btn_ch(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message("Mentionne le **salon de bienvenue** (#salon) ou `disable` :", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        if msg.content.lower() == "disable":
            self.cfg.pop("welcome_channel", None)
        elif msg.channel_mentions:
            self.cfg["welcome_channel"] = msg.channel_mentions[0].id
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Message salon ──
    @discord.ui.button(label="💬 Message salon", style=discord.ButtonStyle.primary, row=0)
    async def btn_msg(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message(
            "Envoie le **message de bienvenue** :\n`{mention}` `{name}` `{server}` `{count}`", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        self.cfg["welcome_message"] = msg.content
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Message MP ──
    @discord.ui.button(label="📩 Message MP", style=discord.ButtonStyle.primary, row=0)
    async def btn_dm(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message(
            "Envoie le **message MP** pour les nouveaux membres, ou `disable` pour désactiver :", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        if msg.content.lower() == "disable":
            self.cfg["welcome_dm"] = False
            self.cfg.pop("welcome_dm_message", None)
        else:
            self.cfg["welcome_dm"] = True
            self.cfg["welcome_dm_message"] = msg.content
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Rôle auto ──
    @discord.ui.button(label="🎭 Rôle auto", style=discord.ButtonStyle.primary, row=0)
    async def btn_role(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message("Mentionne le **rôle automatique** (@role) ou `disable` :", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        if msg.content.lower() == "disable":
            self.cfg.pop("auto_role", None)
        elif msg.role_mentions:
            self.cfg["auto_role"] = msg.role_mentions[0].id
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Image only ──
    @discord.ui.button(label="🖼️ Image only", style=discord.ButtonStyle.secondary, row=1)
    async def btn_img(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message(
            "Gestion image-only :\n• `add #salon`\n• `remove #salon`\n• `clear`", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
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
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Test bienvenue ──
    @discord.ui.button(label="🧪 Tester", style=discord.ButtonStyle.success, row=1)
    async def btn_test(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.defer()
        await on_member_join(interaction.user)
        await interaction.channel.send(embed=e_ok("Test envoyé !"), delete_after=4)


# ═══════════════════════════════════════════════════════════
#  VIEW : !leave  (Message de départ des membres)
# ═══════════════════════════════════════════════════════════

def build_leave_embed(cfg, guild):
    embed = discord.Embed(
        title="👋 Config — Départ des membres",
        description="Clique sur un bouton pour modifier un paramètre.\nChangements sauvegardés **immédiatement**.",
        color=0x95a5a6
    )
    lc = cfg.get("leave_channel")
    embed.add_field(name="📢 Salon départ",
        value=f"<#{lc}>" if lc else "❌ Non configuré", inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    lm = cfg.get("leave_message", "*(par défaut)*")
    embed.add_field(name="💬 Message salon",
        value=f"```{lm[:100]}```", inline=False)

    embed.set_footer(text="Variables : {mention} {name} {server} {count}  •  Expire dans 5 min")
    return embed


class LeaveView(discord.ui.View):
    def __init__(self, cfg, guild, author):
        super().__init__(timeout=300)
        self.cfg    = cfg
        self.guild  = guild
        self.author = author

    def is_author(self, interaction):
        return interaction.user.id == self.author.id

    async def _refresh(self, interaction):
        await interaction.message.edit(
            embed=build_leave_embed(self.cfg, self.guild),
            view=LeaveView(self.cfg, self.guild, self.author)
        )

    # ── Salon départ ──
    @discord.ui.button(label="📢 Salon départ", style=discord.ButtonStyle.primary, row=0)
    async def btn_ch(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message("Mentionne le **salon de départ** (#salon) ou `disable` :", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        if msg.content.lower() == "disable":
            self.cfg.pop("leave_channel", None)
        elif msg.channel_mentions:
            self.cfg["leave_channel"] = msg.channel_mentions[0].id
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Message salon ──
    @discord.ui.button(label="💬 Message salon", style=discord.ButtonStyle.primary, row=0)
    async def btn_msg(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message(
            "Envoie le **message de départ** :\n`{mention}` `{name}` `{server}` `{count}`", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        self.cfg["leave_message"] = msg.content
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Test départ ──
    @discord.ui.button(label="🧪 Tester", style=discord.ButtonStyle.success, row=1)
    async def btn_test(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.defer()
        await on_member_remove(interaction.user)
        await interaction.channel.send(embed=e_ok("Test envoyé !"), delete_after=4)


# ═══════════════════════════════════════════════════════════
#  VIEW : !mod  (Anti-spam / Anti-mention / Anti-link)
# ═══════════════════════════════════════════════════════════

def build_mod_embed(cfg):
    embed = discord.Embed(
        title="🛡️ Config — Modération automatique",
        description="Clique sur un bouton pour modifier. Changements sauvegardés **immédiatement**.",
        color=0xe74c3c
    )

    spam_on = cfg.get("antispam_enabled", False)
    sl = cfg.get("antispam_limit", 5)
    ss = cfg.get("antispam_seconds", 5)
    st = cfg.get("antispam_timeout", 60)
    embed.add_field(name="🚫 Anti-spam",
        value=f"{'✅ Activé' if spam_on else '❌ Désactivé'}\n`{sl} msgs / {ss}s → timeout {st}s`",
        inline=False)

    men_on = cfg.get("antimention_enabled", False)
    ml = cfg.get("antimention_limit", 3)
    ms = cfg.get("antimention_seconds", 10)
    mt = cfg.get("antimention_timeout", 60)
    embed.add_field(name="📣 Anti-mention",
        value=f"{'✅ Activé' if men_on else '❌ Désactivé'}\n`{ml} mentions / {ms}s → timeout {mt}s`",
        inline=False)

    lnk_on = cfg.get("antilink_enabled", False)
    ll = cfg.get("antilink_limit", 2)
    ls = cfg.get("antilink_seconds", 10)
    lt = cfg.get("antilink_timeout", 60)
    embed.add_field(name="🔗 Anti-link",
        value=f"{'✅ Activé' if lnk_on else '❌ Désactivé'}\n`{ll} liens / {ls}s → timeout {lt}s`",
        inline=False)

    embed.set_footer(text="Format config : set <nombre> <secondes> <timeout_secs>  •  Expire dans 5 min")
    return embed


class ModView(discord.ui.View):
    def __init__(self, cfg, author):
        super().__init__(timeout=300)
        self.cfg    = cfg
        self.author = author

    def is_author(self, interaction):
        return interaction.user.id == self.author.id

    async def _refresh(self, interaction):
        await interaction.message.edit(
            embed=build_mod_embed(self.cfg),
            view=ModView(self.cfg, self.author)
        )

    async def _handle_protection(self, interaction, key_prefix, label, default_limit, default_secs, default_timeout):
        if not self.is_author(interaction):
            return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message(
            f"Configure **{label}** :\n"
            f"• `on` — activer\n"
            f"• `off` — désactiver\n"
            f"• `set <nombre> <secondes> <timeout_secs>` — ex: `set {default_limit} {default_secs} {default_timeout}`",
            ephemeral=True
        )
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        parts = msg.content.strip().split()
        cmd = parts[0].lower()
        if cmd == "on":
            self.cfg[f"{key_prefix}_enabled"] = True
        elif cmd == "off":
            self.cfg[f"{key_prefix}_enabled"] = False
        elif cmd == "set" and len(parts) >= 4:
            try:
                self.cfg[f"{key_prefix}_limit"]   = int(parts[1])
                self.cfg[f"{key_prefix}_seconds"]  = int(parts[2])
                self.cfg[f"{key_prefix}_timeout"]  = int(parts[3])
                self.cfg[f"{key_prefix}_enabled"]  = True
            except ValueError:
                pass
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    @discord.ui.button(label="🚫 Anti-spam", style=discord.ButtonStyle.danger, row=0)
    async def btn_spam(self, interaction: discord.Interaction, _):
        await self._handle_protection(interaction, "antispam", "Anti-spam", 5, 5, 60)

    @discord.ui.button(label="📣 Anti-mention", style=discord.ButtonStyle.danger, row=0)
    async def btn_mention(self, interaction: discord.Interaction, _):
        await self._handle_protection(interaction, "antimention", "Anti-mention", 3, 10, 60)

    @discord.ui.button(label="🔗 Anti-link", style=discord.ButtonStyle.danger, row=0)
    async def btn_link(self, interaction: discord.Interaction, _):
        await self._handle_protection(interaction, "antilink", "Anti-link", 2, 10, 60)


# ═══════════════════════════════════════════════════════════
#  VIEW : !reactauto  (Réactions automatiques par salon)
# ═══════════════════════════════════════════════════════════

def build_reactauto_embed(cfg, guild):
    embed = discord.Embed(
        title="🤖 Config — Réactions automatiques",
        description="Le bot ajoute automatiquement une réaction à **chaque message** posté dans les salons configurés.\nChangements sauvegardés **immédiatement**.",
        color=0xf1c40f
    )
    reactauto = cfg.get("reactauto", {})
    if not reactauto:
        embed.add_field(name="📋 Salons configurés", value="*(aucun)*", inline=False)
    else:
        lines = []
        for cid, emojis in reactauto.items():
            lines.append(f"<#{cid}> → {' '.join(emojis)}")
        embed.add_field(name="📋 Salons configurés", value="\n".join(lines), inline=False)

    embed.set_footer(text="Expire dans 5 min")
    return embed


class ReactAutoView(discord.ui.View):
    def __init__(self, cfg, guild, author):
        super().__init__(timeout=300)
        self.cfg    = cfg
        self.guild  = guild
        self.author = author

    def is_author(self, interaction):
        return interaction.user.id == self.author.id

    async def _refresh(self, interaction):
        await interaction.message.edit(
            embed=build_reactauto_embed(self.cfg, self.guild),
            view=ReactAutoView(self.cfg, self.guild, self.author)
        )

    # ── Ajouter / Modifier ──
    @discord.ui.button(label="➕ Ajouter salon", style=discord.ButtonStyle.success, row=0)
    async def btn_add(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message(
            "Mentionne le **salon** puis le(s) **emoji(s)** à la suite, séparés par des espaces.\n"
            "Ex : `#annonces 👍 🎉` ou `#general <:pouce:123456789012345678>`",
            ephemeral=True
        )
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return

        if not msg.channel_mentions:
            try: await msg.delete()
            except: pass
            return await interaction.followup.send(embed=e_err("Aucun salon mentionné."), ephemeral=True)

        channel = msg.channel_mentions[0]
        content = msg.content.replace(channel.mention, "").replace(f"<#{channel.id}>", "")
        emojis = content.strip().split()

        if not emojis:
            try: await msg.delete()
            except: pass
            return await interaction.followup.send(embed=e_err("Aucun emoji fourni."), ephemeral=True)

        if "reactauto" not in self.cfg:
            self.cfg["reactauto"] = {}
        self.cfg["reactauto"][str(channel.id)] = emojis
        save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Retirer ──
    @discord.ui.button(label="➖ Retirer salon", style=discord.ButtonStyle.danger, row=0)
    async def btn_remove(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_message("Mentionne le **salon** à retirer :", ephemeral=True)
        msg = await wait_response(bot, self.author, interaction.channel)
        if not msg: return
        if msg.channel_mentions:
            cid = str(msg.channel_mentions[0].id)
            self.cfg.get("reactauto", {}).pop(cid, None)
            save_config(config)
        try: await msg.delete()
        except: pass
        await self._refresh(interaction)

    # ── Tout effacer ──
    @discord.ui.button(label="🗑️ Tout effacer", style=discord.ButtonStyle.secondary, row=0)
    async def btn_clear(self, interaction: discord.Interaction, _):
        if not self.is_author(interaction): return await interaction.response.send_message("❌", ephemeral=True)
        self.cfg["reactauto"] = {}
        save_config(config)
        await interaction.response.send_message(embed=e_ok("Toutes les réactions auto ont été supprimées."), ephemeral=True)
        await self._refresh(interaction)


# ─────────────────────────────────────────
#  COMMANDES — PERSONNALISATION DU BOT (owner only)
# ─────────────────────────────────────────

@bot.command(name="setpp")
@commands.is_owner()
async def setpp_cmd(ctx, url: str = None):
    """Change la photo de profil du bot. Lien direct ou image en pièce jointe."""
    image_bytes = await get_image_from_ctx(ctx, url)
    if not image_bytes:
        return await ctx.send(embed=e_err("Fournis un **lien direct** vers une image, ou attache une image au message."))
    try:
        await bot.user.edit(avatar=image_bytes)
        await ctx.send(embed=e_ok("Photo de profil mise à jour !"))
    except discord.HTTPException as e:
        await ctx.send(embed=e_err(f"Discord a refusé l'image ({e})."))

@bot.command(name="setbanner")
@commands.is_owner()
async def setbanner_cmd(ctx, url: str = None):
    """Change la bannière du bot. Lien direct ou image en pièce jointe."""
    image_bytes = await get_image_from_ctx(ctx, url)
    if not image_bytes:
        return await ctx.send(embed=e_err("Fournis un **lien direct** vers une image, ou attache une image au message."))
    try:
        await bot.user.edit(banner=image_bytes)
        await ctx.send(embed=e_ok("Bannière mise à jour !"))
    except discord.HTTPException as e:
        await ctx.send(embed=e_err(f"Discord a refusé l'image ({e})."))

@bot.command(name="setbio")
@commands.is_owner()
async def setbio_cmd(ctx, *, texte: str = None):
    """Change la bio (description) du bot affichée sur son profil."""
    if not texte:
        return await ctx.send(embed=e_err("Fournis un texte. Ex : `!setbio Le bot officiel d'Horizon RP !`"))
    if len(texte) > 400:
        return await ctx.send(embed=e_err("Le texte est trop long (max 400 caractères)."))
    try:
        await bot.http.request(Route("PATCH", "/applications/@me"), json={"description": texte})
        await ctx.send(embed=e_ok("Bio mise à jour !", texte))
    except discord.HTTPException as e:
        await ctx.send(embed=e_err(f"Discord a refusé la modification ({e})."))


# ─────────────────────────────────────────
#  COMMANDES PRINCIPALES
# ─────────────────────────────────────────

@bot.command(name="join")
@commands.has_permissions(manage_guild=True)
async def join_cmd(ctx):
    """Panneau config arrivée membres."""
    cfg = guild_config(ctx.guild.id)
    await ctx.send(embed=build_join_embed(cfg, ctx.guild), view=JoinView(cfg, ctx.guild, ctx.author))

@bot.command(name="mod")
@commands.has_permissions(manage_guild=True)
async def mod_cmd(ctx):
    """Panneau config modération automatique."""
    cfg = guild_config(ctx.guild.id)
    await ctx.send(embed=build_mod_embed(cfg), view=ModView(cfg, ctx.author))

@bot.command(name="leave")
@commands.has_permissions(manage_guild=True)
async def leave_cmd(ctx):
    """Panneau config départ membres."""
    cfg = guild_config(ctx.guild.id)
    await ctx.send(embed=build_leave_embed(cfg, ctx.guild), view=LeaveView(cfg, ctx.guild, ctx.author))

@bot.command(name="reactauto")
@commands.has_permissions(manage_guild=True)
async def reactauto_cmd(ctx):
    """Panneau config réactions automatiques."""
    cfg = guild_config(ctx.guild.id)
    await ctx.send(embed=build_reactauto_embed(cfg, ctx.guild), view=ReactAutoView(cfg, ctx.guild, ctx.author))

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Commandes disponibles", color=0x9b59b6)
    embed.add_field(name="🎉 !join", value="Panneau interactif : salon bienvenue, message, MP, rôle auto, image only", inline=False)
    embed.add_field(name="👋 !leave", value="Panneau interactif : salon départ, message de départ", inline=False)
    embed.add_field(name="🛡️ !mod", value="Panneau interactif : anti-spam, anti-mention, anti-link", inline=False)
    embed.add_field(name="🤖 !reactauto", value="Panneau interactif : réactions automatiques par salon", inline=False)
    embed.add_field(name="⚙️ !config", value="Voir toute la configuration actuelle", inline=False)
    embed.add_field(name="🧪 !testwelcome", value="Simuler une arrivée de membre", inline=False)
    embed.add_field(
        name="🎨 Personnalisation du bot (propriétaire uniquement)",
        value="`!setpp <lien ou image>` — photo de profil\n"
              "`!setbanner <lien ou image>` — bannière\n"
              "`!setbio <texte>` — bio / description",
        inline=False
    )
    embed.set_footer(text="Préfixe : !")
    await ctx.send(embed=embed)

@bot.command(name="config")
@commands.has_permissions(manage_guild=True)
async def config_cmd(ctx):
    cfg = guild_config(ctx.guild.id)
    e1 = build_join_embed(cfg, ctx.guild)
    e1.title = "⚙️ Config — Arrivée"
    e1b = build_leave_embed(cfg, ctx.guild)
    e1b.title = "⚙️ Config — Départ"
    e2 = build_mod_embed(cfg)
    e2.title = "⚙️ Config — Modération"
    e3 = build_reactauto_embed(cfg, ctx.guild)
    e3.title = "⚙️ Config — Réactions auto"
    await ctx.send(embeds=[e1, e1b, e2, e3])

@bot.command(name="testwelcome")
@commands.has_permissions(manage_guild=True)
async def test_welcome(ctx):
    await on_member_join(ctx.author)
    await ctx.send(embed=e_ok("Test envoyé !"), delete_after=4)

# ─────────────────────────────────────────
#  ERREURS
# ─────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=e_err("Permission refusée."))
    elif isinstance(error, commands.NotOwner):
        await ctx.send(embed=e_err("Commande réservée au propriétaire du bot."))
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
