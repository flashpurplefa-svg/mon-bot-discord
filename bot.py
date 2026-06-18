import discord
from discord.ext import commands
import json
import os
import time
import asyncio
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

# ─────────────────────────────────────────
#  BOT SETUP
# ─────────────────────────────────────────

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

spam_tracker = defaultdict(list)

# Sessions !join actives (guild_id -> True)
join_sessions = set()

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def guild_config(guild_id):
    key = str(guild_id)
    if key not in config:
        config[key] = {}
    return config[key]

def embed_ok(title, desc):
    return discord.Embed(title=f"✅ {title}", description=desc, color=0x2ecc71)

def embed_err(desc):
    return discord.Embed(title="❌ Erreur", description=desc, color=0xe74c3c)

def embed_info(title, desc):
    return discord.Embed(title=f"ℹ️ {title}", description=desc, color=0x3498db)

def embed_question(step, total, question, tip=""):
    e = discord.Embed(
        title=f"🔧 Configuration — Étape {step}/{total}",
        description=f"**{question}**",
        color=0x9b59b6
    )
    if tip:
        e.set_footer(text=tip)
    return e

async def ask(ctx, bot, question_embed, timeout=60):
    """Envoie une question et attend la réponse de l'auteur dans le même salon."""
    await ctx.send(embed=question_embed)
    try:
        msg = await bot.wait_for(
            "message",
            timeout=timeout,
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel
        )
        return msg
    except asyncio.TimeoutError:
        return None

# ─────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name="!help"
    ))

@bot.event
async def on_member_join(member):
    cfg = guild_config(member.guild.id)

    # ── Message salon bienvenue ──
    if cfg.get("welcome_channel"):
        channel = member.guild.get_channel(cfg["welcome_channel"])
        if channel:
            msg = cfg.get("welcome_message", "Bienvenue {mention} sur **{server}** ! 🎉")
            msg = msg.replace("{mention}", member.mention)\
                     .replace("{name}", member.name)\
                     .replace("{server}", member.guild.name)\
                     .replace("{count}", str(member.guild.member_count))
            embed = discord.Embed(description=msg, color=0x9b59b6)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    # ── Message MP ──
    if cfg.get("welcome_dm"):
        msg_dm = cfg.get("welcome_dm_message", "Bienvenue sur **{server}** ! 🎉")
        msg_dm = msg_dm.replace("{mention}", member.mention)\
                       .replace("{name}", member.name)\
                       .replace("{server}", member.guild.name)\
                       .replace("{count}", str(member.guild.member_count))
        try:
            embed_dm = discord.Embed(description=msg_dm, color=0x9b59b6)
            embed_dm.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            await member.send(embed=embed_dm)
        except discord.Forbidden:
            pass

    # ── Rôle automatique ──
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

    cfg = guild_config(message.guild.id)

    # ── Image only ──
    if message.channel.id in cfg.get("image_only_channels", []):
        has_image = any(
            a.content_type and a.content_type.startswith("image")
            for a in message.attachments
        )
        if not has_image:
            try:
                await message.delete()
                warn = await message.channel.send(
                    f"{message.author.mention} ❌ Ce salon accepte **uniquement des images** !"
                )
                await warn.delete(delay=5)
            except discord.Forbidden:
                pass
            return

    # ── Anti-spam ──
    if cfg.get("antispam_enabled"):
        limit = cfg.get("antispam_limit", 5)
        seconds = cfg.get("antispam_seconds", 5)
        now = time.time()
        uid = message.author.id
        spam_tracker[uid] = [t for t in spam_tracker[uid] if now - t < seconds]
        spam_tracker[uid].append(now)

        if len(spam_tracker[uid]) >= limit:
            try:
                await message.delete()
                until = discord.utils.utcnow() + discord.utils.MISSING.__class__.__new__(discord.utils.MISSING.__class__)
                import datetime
                until = discord.utils.utcnow() + datetime.timedelta(seconds=60)
                await message.author.timeout(until, reason="Anti-spam")
            except Exception:
                pass
            warn = await message.channel.send(
                f"{message.author.mention} ⛔ **Anti-spam** : trop de messages ! Timeout 60s."
            )
            await warn.delete(delay=8)
            spam_tracker[uid] = []
            return

    await bot.process_commands(message)

# ─────────────────────────────────────────
#  COMMANDE !join  ← NOUVEAU
# ─────────────────────────────────────────

@bot.command(name="join")
@commands.has_permissions(manage_guild=True)
async def join_setup(ctx):
    """Assistant interactif de configuration de l'arrivée des membres."""

    if ctx.guild.id in join_sessions:
        await ctx.send(embed=embed_err("Une configuration est déjà en cours dans ce serveur !"))
        return

    join_sessions.add(ctx.guild.id)
    cfg = guild_config(ctx.guild.id)

    try:
        # ── Intro ──
        intro = discord.Embed(
            title="🛠️ Assistant de configuration — Arrivée des membres",
            description=(
                "Je vais te poser **6 questions** pour configurer l'accueil de tes membres.\n\n"
                "Réponds à chaque question dans ce salon.\n"
                "Tape `skip` pour ignorer une étape.\n"
                "Tu as **60 secondes** par réponse."
            ),
            color=0x9b59b6
        )
        intro.add_field(name="Ce qu'on va configurer :", value=(
            "1️⃣ Salon de bienvenue\n"
            "2️⃣ Message de bienvenue (salon)\n"
            "3️⃣ Message privé (MP)\n"
            "4️⃣ Contenu du MP\n"
            "5️⃣ Rôle automatique\n"
            "6️⃣ Récap & confirmation"
        ), inline=False)
        await ctx.send(embed=intro)
        await asyncio.sleep(1)

        # ════════════════════════════
        # ÉTAPE 1 — Salon bienvenue
        # ════════════════════════════
        q1 = embed_question(1, 5, "Dans quel salon envoyer le message de bienvenue ?",
                            "Mentionne le salon avec # ou tape skip")
        msg = await ask(ctx, bot, q1)
        if msg is None:
            await ctx.send(embed=embed_err("⏰ Temps écoulé. Configuration annulée."))
            join_sessions.discard(ctx.guild.id)
            return

        if msg.content.lower() != "skip":
            if msg.channel_mentions:
                cfg["welcome_channel"] = msg.channel_mentions[0].id
                welcome_ch = msg.channel_mentions[0]
            else:
                await ctx.send(embed=embed_err("Salon introuvable. Étape ignorée."))
                welcome_ch = None
        else:
            welcome_ch = None

        # ════════════════════════════
        # ÉTAPE 2 — Message bienvenue
        # ════════════════════════════
        q2 = embed_question(2, 5,
            "Quel message afficher dans le salon de bienvenue ?",
            "Variables dispo : {mention} {name} {server} {count} — ou tape skip pour le message par défaut"
        )
        msg2 = await ask(ctx, bot, q2)
        if msg2 is None:
            await ctx.send(embed=embed_err("⏰ Temps écoulé. Configuration annulée."))
            join_sessions.discard(ctx.guild.id)
            return

        if msg2.content.lower() != "skip":
            cfg["welcome_message"] = msg2.content
            welcome_msg_preview = msg2.content
        else:
            cfg.pop("welcome_message", None)
            welcome_msg_preview = "*(message par défaut)*"

        # ════════════════════════════
        # ÉTAPE 3 — MP oui/non
        # ════════════════════════════
        q3 = embed_question(3, 5,
            "Veux-tu envoyer un message privé (MP) aux nouveaux membres ?",
            "Réponds : oui / non"
        )
        msg3 = await ask(ctx, bot, q3)
        if msg3 is None:
            await ctx.send(embed=embed_err("⏰ Temps écoulé. Configuration annulée."))
            join_sessions.discard(ctx.guild.id)
            return

        dm_enabled = msg3.content.lower() in ("oui", "o", "yes", "y")
        cfg["welcome_dm"] = dm_enabled
        dm_msg_preview = "*(désactivé)*"

        # ════════════════════════════
        # ÉTAPE 4 — Contenu MP
        # ════════════════════════════
        if dm_enabled:
            q4 = embed_question(4, 5,
                "Quel message envoyer en MP au nouveau membre ?",
                "Variables dispo : {name} {server} — ou skip pour le message par défaut"
            )
            msg4 = await ask(ctx, bot, q4)
            if msg4 is None:
                await ctx.send(embed=embed_err("⏰ Temps écoulé. Configuration annulée."))
                join_sessions.discard(ctx.guild.id)
                return

            if msg4.content.lower() != "skip":
                cfg["welcome_dm_message"] = msg4.content
                dm_msg_preview = msg4.content
            else:
                cfg.pop("welcome_dm_message", None)
                dm_msg_preview = "*(message par défaut)*"
        else:
            cfg.pop("welcome_dm_message", None)

        # ════════════════════════════
        # ÉTAPE 5 — Rôle automatique
        # ════════════════════════════
        q5 = embed_question(5, 5,
            "Quel rôle donner automatiquement aux nouveaux membres ?",
            "Mentionne le rôle avec @ — ou tape skip pour ignorer"
        )
        msg5 = await ask(ctx, bot, q5)
        if msg5 is None:
            await ctx.send(embed=embed_err("⏰ Temps écoulé. Configuration annulée."))
            join_sessions.discard(ctx.guild.id)
            return

        role_preview = "*(désactivé)*"
        if msg5.content.lower() != "skip":
            if msg5.role_mentions:
                cfg["auto_role"] = msg5.role_mentions[0].id
                role_preview = f"@{msg5.role_mentions[0].name}"
            else:
                await ctx.send(embed=embed_err("Rôle introuvable. Étape ignorée."))

        # ════════════════════════════
        # ÉTAPE 6 — Récap
        # ════════════════════════════
        save_config(config)

        recap = discord.Embed(
            title="✅ Configuration sauvegardée !",
            description="Voici un résumé de ce qui a été configuré :",
            color=0x2ecc71
        )
        recap.add_field(
            name="📢 Salon bienvenue",
            value=welcome_ch.mention if welcome_ch else "❌ Non configuré",
            inline=False
        )
        recap.add_field(
            name="💬 Message salon",
            value=welcome_msg_preview[:200],
            inline=False
        )
        recap.add_field(
            name="📩 Message MP",
            value=f"{'✅ Activé' if dm_enabled else '❌ Désactivé'}\n{dm_msg_preview[:200] if dm_enabled else ''}",
            inline=False
        )
        recap.add_field(
            name="🎭 Rôle automatique",
            value=role_preview,
            inline=False
        )
        recap.set_footer(text="Utilise !testwelcome pour tester • !config pour voir tout • !join pour reconfigurer")
        await ctx.send(embed=recap)

    finally:
        join_sessions.discard(ctx.guild.id)

# ─────────────────────────────────────────
#  COMMANDE !help
# ─────────────────────────────────────────

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Liste des commandes", color=0x9b59b6)

    embed.add_field(name="🛠️ Configuration rapide", value=(
        "`!join` — **Assistant interactif** : configure le salon de bienvenue,\n"
        "le message, le MP et le rôle automatique en une seule commande !\n"
    ), inline=False)

    embed.add_field(name="🎉 Bienvenue (commandes directes)", value=(
        "`!setwelcome #salon` — Salon de bienvenue\n"
        "`!setwelcomemsg <msg>` — Message salon\n"
        "`!setwelcomedm <msg>` — Message MP\n"
        "`!toggledm` — Activer/désactiver le MP\n"
        "`!testwelcome` — Tester la bienvenue\n"
        "`!disablewelcome` — Tout désactiver\n"
        "Variables : `{mention}` `{name}` `{server}` `{count}`"
    ), inline=False)

    embed.add_field(name="🎭 Rôle automatique", value=(
        "`!setautorole @role` — Rôle à l'arrivée\n"
        "`!disableautorole` — Désactiver"
    ), inline=False)

    embed.add_field(name="🚫 Anti-spam", value=(
        "`!antispam on/off` — Activer/désactiver\n"
        "`!antispam set <msgs> <secs>` — Ex: `!antispam set 5 4`"
    ), inline=False)

    embed.add_field(name="🖼️ Salon image only", value=(
        "`!imageonly add #salon` — Images uniquement\n"
        "`!imageonly remove #salon` — Retirer\n"
        "`!imageonly list` — Voir la liste"
    ), inline=False)

    embed.add_field(name="⚙️ Autre", value=(
        "`!config` — Voir toute la configuration"
    ), inline=False)

    embed.set_footer(text="Préfixe : !  |  Bot de gestion serveur")
    await ctx.send(embed=embed)

# ─────────────────────────────────────────
#  COMMANDES BIENVENUE DIRECTES
# ─────────────────────────────────────────

@bot.command(name="setwelcome")
@commands.has_permissions(manage_guild=True)
async def set_welcome(ctx, channel: discord.TextChannel):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_channel"] = channel.id
    save_config(config)
    await ctx.send(embed=embed_ok("Salon configuré", f"Bienvenue → {channel.mention}"))

@bot.command(name="setwelcomemsg")
@commands.has_permissions(manage_guild=True)
async def set_welcome_msg(ctx, *, message: str):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_message"] = message
    save_config(config)
    await ctx.send(embed=embed_ok("Message mis à jour", f"> {message}"))

@bot.command(name="setwelcomedm")
@commands.has_permissions(manage_guild=True)
async def set_welcome_dm(ctx, *, message: str):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_dm"] = True
    cfg["welcome_dm_message"] = message
    save_config(config)
    await ctx.send(embed=embed_ok("Message MP configuré", f"> {message}"))

@bot.command(name="toggledm")
@commands.has_permissions(manage_guild=True)
async def toggle_dm(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_dm"] = not cfg.get("welcome_dm", False)
    save_config(config)
    state = "activé ✅" if cfg["welcome_dm"] else "désactivé ❌"
    await ctx.send(embed=embed_ok("MP de bienvenue", f"Message privé {state}"))

@bot.command(name="testwelcome")
@commands.has_permissions(manage_guild=True)
async def test_welcome(ctx):
    await on_member_join(ctx.author)
    await ctx.send(embed=embed_ok("Test envoyé !", "Simulation d'arrivée effectuée."))

@bot.command(name="disablewelcome")
@commands.has_permissions(manage_guild=True)
async def disable_welcome(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg.pop("welcome_channel", None)
    cfg["welcome_dm"] = False
    save_config(config)
    await ctx.send(embed=embed_ok("Bienvenue désactivée", "Plus aucun message de bienvenue ne sera envoyé."))

# ─────────────────────────────────────────
#  RÔLE AUTO
# ─────────────────────────────────────────

@bot.command(name="setautorole")
@commands.has_permissions(manage_roles=True)
async def set_auto_role(ctx, role: discord.Role):
    cfg = guild_config(ctx.guild.id)
    cfg["auto_role"] = role.id
    save_config(config)
    await ctx.send(embed=embed_ok("Rôle auto configuré", f"**{role.name}** sera donné à chaque nouveau membre."))

@bot.command(name="disableautorole")
@commands.has_permissions(manage_roles=True)
async def disable_auto_role(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg.pop("auto_role", None)
    save_config(config)
    await ctx.send(embed=embed_ok("Rôle auto désactivé", "Plus aucun rôle automatique."))

# ─────────────────────────────────────────
#  ANTI-SPAM
# ─────────────────────────────────────────

@bot.command(name="antispam")
@commands.has_permissions(manage_guild=True)
async def antispam(ctx, action: str, *args):
    cfg = guild_config(ctx.guild.id)
    action = action.lower()

    if action == "on":
        cfg["antispam_enabled"] = True
        save_config(config)
        limit = cfg.get("antispam_limit", 5)
        secs = cfg.get("antispam_seconds", 5)
        await ctx.send(embed=embed_ok("Anti-spam activé", f"**{limit} messages** en **{secs}s** → timeout 60s"))

    elif action == "off":
        cfg["antispam_enabled"] = False
        save_config(config)
        await ctx.send(embed=embed_ok("Anti-spam désactivé", "L'anti-spam est éteint."))

    elif action == "set":
        if len(args) < 2:
            await ctx.send(embed=embed_err("Usage : `!antispam set <messages> <secondes>`"))
            return
        try:
            limit, secs = int(args[0]), int(args[1])
            cfg["antispam_limit"] = limit
            cfg["antispam_seconds"] = secs
            save_config(config)
            await ctx.send(embed=embed_ok("Anti-spam configuré", f"**{limit} msgs** en **{secs}s** → timeout."))
        except ValueError:
            await ctx.send(embed=embed_err("Utilise des nombres entiers."))
    else:
        await ctx.send(embed=embed_err("Actions : `on` / `off` / `set <msgs> <secs>`"))

# ─────────────────────────────────────────
#  IMAGE ONLY
# ─────────────────────────────────────────

@bot.command(name="imageonly")
@commands.has_permissions(manage_channels=True)
async def image_only(ctx, action: str, channel: discord.TextChannel = None):
    cfg = guild_config(ctx.guild.id)
    if "image_only_channels" not in cfg:
        cfg["image_only_channels"] = []
    action = action.lower()

    if action == "add":
        if not channel:
            await ctx.send(embed=embed_err("`!imageonly add #salon`"))
            return
        if channel.id not in cfg["image_only_channels"]:
            cfg["image_only_channels"].append(channel.id)
            save_config(config)
        await ctx.send(embed=embed_ok("Salon restreint", f"{channel.mention} → images uniquement."))

    elif action == "remove":
        if not channel:
            await ctx.send(embed=embed_err("`!imageonly remove #salon`"))
            return
        cfg["image_only_channels"] = [c for c in cfg["image_only_channels"] if c != channel.id]
        save_config(config)
        await ctx.send(embed=embed_ok("Restriction retirée", f"{channel.mention} → messages autorisés à nouveau."))

    elif action == "list":
        lst = cfg.get("image_only_channels", [])
        text = "\n".join(f"• <#{c}>" for c in lst) if lst else "*(aucun)*"
        await ctx.send(embed=embed_info("Salons image only", text))
    else:
        await ctx.send(embed=embed_err("`add #salon` / `remove #salon` / `list`"))

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

@bot.command(name="config")
@commands.has_permissions(manage_guild=True)
async def show_config(ctx):
    cfg = guild_config(ctx.guild.id)
    embed = discord.Embed(title="⚙️ Configuration actuelle", color=0xf39c12)

    wc = cfg.get("welcome_channel")
    wm = cfg.get("welcome_message", "*(par défaut)*")
    embed.add_field(name="🎉 Salon bienvenue",
        value=f"{f'<#{wc}>' if wc else '❌'}\n{wm[:100]}", inline=False)

    dm_on = cfg.get("welcome_dm", False)
    dm_msg = cfg.get("welcome_dm_message", "*(par défaut)*")
    embed.add_field(name="📩 MP bienvenue",
        value=f"{'✅' if dm_on else '❌'} {dm_msg[:100] if dm_on else ''}", inline=False)

    ar = cfg.get("auto_role")
    role = ctx.guild.get_role(ar)
    embed.add_field(name="🎭 Rôle auto",
        value=f"@{role.name}" if role else "❌", inline=False)

    spam_on = cfg.get("antispam_enabled", False)
    limit = cfg.get("antispam_limit", 5)
    secs = cfg.get("antispam_seconds", 5)
    embed.add_field(name="🚫 Anti-spam",
        value=f"{'✅' if spam_on else '❌'} — {limit} msgs / {secs}s", inline=False)

    imgs = cfg.get("image_only_channels", [])
    embed.add_field(name="🖼️ Image only",
        value="\n".join(f"<#{c}>" for c in imgs) or "*(aucun)*", inline=False)

    await ctx.send(embed=embed)

# ─────────────────────────────────────────
#  ERREURS
# ─────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=embed_err("Permission refusée."))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=embed_err("Argument manquant. Tape `!help`"))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=embed_err("Argument invalide. Tape `!help`"))
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
