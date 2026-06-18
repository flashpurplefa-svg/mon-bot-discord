import discord
from discord.ext import commands
import json
import os
import time
from collections import defaultdict

# ─────────────────────────────────────────
#  CONFIG (sauvegardée dans config.json)
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

# Anti-spam : stocke les timestamps des messages par user
spam_tracker = defaultdict(list)

# ─────────────────────────────────────────
#  HELPER
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

# ─────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name="!help"
    ))

@bot.event
async def on_member_join(member):
    cfg = guild_config(member.guild.id)

    # Message de bienvenue
    if cfg.get("welcome_channel"):
        channel = member.guild.get_channel(cfg["welcome_channel"])
        if channel:
            msg = cfg.get("welcome_message", "Bienvenue {mention} sur **{server}** ! 🎉")
            msg = msg.replace("{mention}", member.mention)
            msg = msg.replace("{name}", member.name)
            msg = msg.replace("{server}", member.guild.name)
            msg = msg.replace("{count}", str(member.guild.member_count))
            embed = discord.Embed(description=msg, color=0x9b59b6)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    # Rôle automatique
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

    # ── Salon image seulement ──
    image_only_channels = cfg.get("image_only_channels", [])
    if message.channel.id in image_only_channels:
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
                # Timeout 60 secondes
                await message.author.timeout(discord.utils.utcnow().__class__.now(
                    tz=None).__class__.fromtimestamp(now + 60))
            except Exception:
                pass
            warn = await message.channel.send(
                f"{message.author.mention} ⛔ **Anti-spam** : tu envoies trop de messages ! Timeout 60s."
            )
            await warn.delete(delay=8)
            spam_tracker[uid] = []
            return

    await bot.process_commands(message)

# ─────────────────────────────────────────
#  COMMANDE : !help
# ─────────────────────────────────────────

@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="📖 Liste des commandes",
        color=0x9b59b6
    )

    embed.add_field(name="🎉 Bienvenue", value="""
`!setwelcome #salon` — Définir le salon de bienvenue
`!setwelcomemsg <message>` — Personnaliser le message
`!testwelcome` — Tester le message de bienvenue
`!disablewelcome` — Désactiver la bienvenue

Variables : `{mention}` `{name}` `{server}` `{count}`
""", inline=False)

    embed.add_field(name="🎭 Rôle automatique", value="""
`!setautorole @role` — Donner un rôle à l'arrivée
`!disableautorole` — Désactiver le rôle auto
""", inline=False)

    embed.add_field(name="🚫 Anti-spam", value="""
`!antispam on` — Activer l'anti-spam
`!antispam off` — Désactiver l'anti-spam
`!antispam set <messages> <secondes>` — Ex: `!antispam set 5 4`
""", inline=False)

    embed.add_field(name="🖼️ Salon image uniquement", value="""
`!imageonly add #salon` — Restreindre à images uniquement
`!imageonly remove #salon` — Retirer la restriction
`!imageonly list` — Voir les salons restreints
""", inline=False)

    embed.add_field(name="⚙️ Infos", value="`!config` — Voir la configuration actuelle", inline=False)

    embed.set_footer(text="Préfixe : !  |  Bot de gestion serveur")
    await ctx.send(embed=embed)

# ─────────────────────────────────────────
#  COMMANDES BIENVENUE
# ─────────────────────────────────────────

@bot.command(name="setwelcome")
@commands.has_permissions(manage_guild=True)
async def set_welcome(ctx, channel: discord.TextChannel):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_channel"] = channel.id
    save_config(config)
    await ctx.send(embed=embed_ok("Bienvenue configurée", f"Salon défini sur {channel.mention}"))

@bot.command(name="setwelcomemsg")
@commands.has_permissions(manage_guild=True)
async def set_welcome_msg(ctx, *, message: str):
    cfg = guild_config(ctx.guild.id)
    cfg["welcome_message"] = message
    save_config(config)
    await ctx.send(embed=embed_ok("Message mis à jour", f"Nouveau message :\n> {message}"))

@bot.command(name="testwelcome")
@commands.has_permissions(manage_guild=True)
async def test_welcome(ctx):
    await on_member_join(ctx.author)
    await ctx.send(embed=embed_ok("Test envoyé", "Message de bienvenue simulé !"))

@bot.command(name="disablewelcome")
@commands.has_permissions(manage_guild=True)
async def disable_welcome(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg.pop("welcome_channel", None)
    save_config(config)
    await ctx.send(embed=embed_ok("Bienvenue désactivée", "Les messages de bienvenue sont désactivés."))

# ─────────────────────────────────────────
#  COMMANDES RÔLE AUTO
# ─────────────────────────────────────────

@bot.command(name="setautorole")
@commands.has_permissions(manage_roles=True)
async def set_auto_role(ctx, role: discord.Role):
    cfg = guild_config(ctx.guild.id)
    cfg["auto_role"] = role.id
    save_config(config)
    await ctx.send(embed=embed_ok("Rôle auto configuré", f"Le rôle **{role.name}** sera donné à chaque nouveau membre."))

@bot.command(name="disableautorole")
@commands.has_permissions(manage_roles=True)
async def disable_auto_role(ctx):
    cfg = guild_config(ctx.guild.id)
    cfg.pop("auto_role", None)
    save_config(config)
    await ctx.send(embed=embed_ok("Rôle auto désactivé", "Plus aucun rôle ne sera attribué automatiquement."))

# ─────────────────────────────────────────
#  COMMANDES ANTI-SPAM
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
        await ctx.send(embed=embed_ok("Anti-spam activé", f"Limite : **{limit} messages** en **{secs}s** → timeout 60s"))

    elif action == "off":
        cfg["antispam_enabled"] = False
        save_config(config)
        await ctx.send(embed=embed_ok("Anti-spam désactivé", "L'anti-spam est maintenant désactivé."))

    elif action == "set":
        if len(args) < 2:
            await ctx.send(embed=embed_err("Usage : `!antispam set <messages> <secondes>`"))
            return
        try:
            limit = int(args[0])
            secs = int(args[1])
            cfg["antispam_limit"] = limit
            cfg["antispam_seconds"] = secs
            save_config(config)
            await ctx.send(embed=embed_ok("Anti-spam configuré", f"**{limit} messages** en **{secs}s** déclenchent le timeout."))
        except ValueError:
            await ctx.send(embed=embed_err("Les valeurs doivent être des nombres entiers."))
    else:
        await ctx.send(embed=embed_err("Actions disponibles : `on` / `off` / `set <messages> <secondes>`"))

# ─────────────────────────────────────────
#  COMMANDES IMAGE ONLY
# ─────────────────────────────────────────

@bot.command(name="imageonly")
@commands.has_permissions(manage_channels=True)
async def image_only(ctx, action: str, channel: discord.TextChannel = None):
    cfg = guild_config(ctx.guild.id)
    action = action.lower()

    if "image_only_channels" not in cfg:
        cfg["image_only_channels"] = []

    if action == "add":
        if not channel:
            await ctx.send(embed=embed_err("Mentionne un salon : `!imageonly add #salon`"))
            return
        if channel.id not in cfg["image_only_channels"]:
            cfg["image_only_channels"].append(channel.id)
            save_config(config)
        await ctx.send(embed=embed_ok("Salon restreint", f"{channel.mention} accepte désormais **uniquement des images**."))

    elif action == "remove":
        if not channel:
            await ctx.send(embed=embed_err("Mentionne un salon : `!imageonly remove #salon`"))
            return
        if channel.id in cfg["image_only_channels"]:
            cfg["image_only_channels"].remove(channel.id)
            save_config(config)
        await ctx.send(embed=embed_ok("Restriction retirée", f"{channel.mention} accepte à nouveau tous les messages."))

    elif action == "list":
        channels = cfg.get("image_only_channels", [])
        if not channels:
            await ctx.send(embed=embed_info("Salons image only", "Aucun salon restreint pour l'instant."))
        else:
            mentions = "\n".join(f"• <#{cid}>" for cid in channels)
            await ctx.send(embed=embed_info("Salons image only", mentions))
    else:
        await ctx.send(embed=embed_err("Actions disponibles : `add #salon` / `remove #salon` / `list`"))

# ─────────────────────────────────────────
#  COMMANDE CONFIG
# ─────────────────────────────────────────

@bot.command(name="config")
@commands.has_permissions(manage_guild=True)
async def show_config(ctx):
    cfg = guild_config(ctx.guild.id)
    embed = discord.Embed(title="⚙️ Configuration actuelle", color=0xf39c12)

    # Bienvenue
    wc = cfg.get("welcome_channel")
    wm = cfg.get("welcome_message", "*(message par défaut)*")
    embed.add_field(
        name="🎉 Bienvenue",
        value=f"Salon : {f'<#{wc}>' if wc else '❌ désactivé'}\nMessage : {wm}",
        inline=False
    )

    # Rôle auto
    ar = cfg.get("auto_role")
    role_name = ctx.guild.get_role(ar).name if ar else None
    embed.add_field(
        name="🎭 Rôle auto",
        value=f"{'@' + role_name if role_name else '❌ désactivé'}",
        inline=False
    )

    # Anti-spam
    spam_on = cfg.get("antispam_enabled", False)
    limit = cfg.get("antispam_limit", 5)
    secs = cfg.get("antispam_seconds", 5)
    embed.add_field(
        name="🚫 Anti-spam",
        value=f"{'✅ activé' if spam_on else '❌ désactivé'} — {limit} msg / {secs}s",
        inline=False
    )

    # Image only
    img_channels = cfg.get("image_only_channels", [])
    img_text = "\n".join(f"<#{c}>" for c in img_channels) if img_channels else "*(aucun)*"
    embed.add_field(name="🖼️ Salons image only", value=img_text, inline=False)

    await ctx.send(embed=embed)

# ─────────────────────────────────────────
#  GESTION ERREURS
# ─────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=embed_err("Tu n'as pas la permission d'utiliser cette commande."))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=embed_err(f"Argument manquant. Tape `!help` pour voir l'usage."))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=embed_err("Argument invalide. Vérifie la commande avec `!help`."))

# ─────────────────────────────────────────
#  LANCEMENT
# ─────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERREUR : Variable DISCORD_TOKEN manquante !")
    exit(1)

bot.run(TOKEN)
