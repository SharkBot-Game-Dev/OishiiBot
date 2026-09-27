import asyncio
import random
import re

import discord
from discord.ext import commands, tasks
import aiosqlite
import dotenv
import os

from janome.tokenizer import Tokenizer

dotenv.load_dotenv()

tokenizer = Tokenizer()

intents = discord.Intents.none()
intents.message_content = True
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="o.", intents=intents, help_command=None)

db: aiosqlite.Connection = None
cursur: aiosqlite.Cursor = None

TASTY_RE = re.compile(r"(.+)おいしい")

try:
    with open("data/ngwords.txt") as read_ngwords:
        ngwords = read_ngwords.read()
except:
    ngwords = ""
    if not ngwords:
        print("NGワードがありません。")

def load_foods(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        return {
            line.strip()
            for line in f
            if line.strip()
        }

FOODS = load_foods("data/foods.txt")

def is_food(word: str) -> bool:
    return word.strip() in FOODS

@bot.event
async def setup_hook():
    global db
    global cursur
    db = await aiosqlite.connect("data.db")
    cursur = await db.cursor()

    await cursur.execute("CREATE TABLE IF NOT EXISTS alert_channel (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, guild_id TEXT NOT NULL UNIQUE)")
    await cursur.execute("CREATE TABLE IF NOT EXISTS alerted_tasty_words (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL, word TEXT NOT NULL)")
    await cursur.execute("CREATE TABLE IF NOT EXISTS tasty_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT NOT NULL UNIQUE)")
    await cursur.execute("CREATE TABLE IF NOT EXISTS bad_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT NOT NULL)")

    await db.commit()

@bot.event
async def on_ready():
    print("起動しました。")

    await cursur.execute('SELECT * FROM tasty_words')
    words = await cursur.fetchall()
    for w in words:
        FOODS.add(w[1])

    sync_tasty_words.start()

    if os.environ.get('SYNC_TREE') == "0":
        return
    await bot.tree.sync()

@tasks.loop(minutes=5)
async def sync_tasty_words():
    await cursur.execute("SELECT word FROM tasty_words")
    words = await cursur.fetchall()

    for (word,) in words:
        FOODS.add(word)

async def process_tasty(message: discord.Message, tasty_word: str):
    try:
        await cursur.execute("""INSERT INTO tasty_words (word)
VALUES (?)
ON CONFLICT(word)
DO UPDATE SET word = ?;""", (str(tasty_word),str(tasty_word),))

        await db.commit()

        await message.add_reaction("🍮")

        await cursur.execute('SELECT * FROM alerted_tasty_words WHERE guild_id = ? AND word = ?;', (str(message.guild.id), str(tasty_word)))
        alerted = await cursur.fetchone()
        if alerted:
            return

        await cursur.execute('SELECT * FROM alert_channel WHERE guild_id = ?;', (str(message.guild.id),))
        alert_channel = await cursur.fetchone()

        # print(alert_channel)

        if not alert_channel:
            return

        channel_id = alert_channel[1]
        channel = message.guild.get_channel(int(channel_id))
        if not channel:
            return

        await channel.send(embed=discord.Embed(color=discord.Color.yellow(), title=f"{tasty_word}おいしい").set_footer(text="おいしいBot").set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url))
            
        await cursur.execute("""INSERT INTO alerted_tasty_words (guild_id, word) VALUES (?, ?)""", (str(message.guild.id), str(tasty_word),))
        await db.commit()

        return
    except Exception as e:
        print(f"process_tasty error: {e}")
        return

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if "おなかすいた" in message.content:
        await cursur.execute('SELECT * FROM tasty_words')
        words = await cursur.fetchall()
        words_list = []
        for w in words:
            words_list.append(w[1])

        if len(words_list) == 0:
            await message.channel.send("残念ながら食べ物がありません..")
            return

        await message.reply(embed=discord.Embed(title="お腹すいた！", description=f"{random.choice(words_list)}とかどう？", color=discord.Color.yellow()))

    tasty = TASTY_RE.search(message.content)
    if tasty:
        if tasty.group(1) in ngwords:
            await message.add_reaction("🤔")
            return

        if not is_food(tasty.group(1)):
            await message.add_reaction("🤔")
            return

        tasty_word = tasty.group(1)
        await process_tasty(message, tasty_word)

    tokens = await asyncio.to_thread(
        lambda: list(tokenizer.tokenize(message.content))
    )

    for token in tokens:
        word = token.surface.strip()

        if token.part_of_speech.split(",")[0] != "名詞":
            continue

        if word not in FOODS:
            continue

        await process_tasty(message, word)
        return

    await bot.process_commands(message)

@bot.hybrid_command(name="help", description="おいしいBotの使い方")
@commands.has_guild_permissions(manage_channels=True)
@commands.guild_only()
async def help(ctx: commands.Context):
    await ctx.send(embed=discord.Embed(title="おいしいBotの使い方", description="""スラッシュコマンド👇️
`/help` このメッセージを表示します。
`/set-channel` 通知するチャンネルを設定します。
`/hungry` 見つけた食べ物をランダムに提示します。

テキストコマンド👇️
`おなかすいた` 見つけた食べ物をランダムに提示します。
`〇〇おいしい` おいしいものを学習させます。（失敗もあり）

その他食べ物がメッセージ内容に含まれていると反応します。
""", color=discord.Color.blue()))

@bot.hybrid_command(name="set-channel", description="通知するチャンネルを設定します。")
@commands.has_guild_permissions(manage_channels=True)
@commands.guild_only()
async def set_channel(ctx: commands.Context, channel: discord.TextChannel):
    await ctx.defer(ephemeral=True)

    await cursur.execute("""INSERT INTO alert_channel (channel_id, guild_id)
VALUES (?, ?)
ON CONFLICT(guild_id)
DO UPDATE SET channel_id = ?;""", (str(channel.id), str(ctx.guild.id), str(channel.id),))

    await db.commit()

    await channel.send("設定完了！\nこれからここにおいしいものを投稿するね！")

    if ctx.interaction:
        await ctx.reply("✅", ephemeral=True)

@bot.hybrid_command(name="hungry", description="見つけた食べ物をランダムに提示します。")
@commands.has_guild_permissions(manage_channels=True)
@commands.guild_only()
async def hungry(ctx: commands.Context):
    await ctx.defer()

    await cursur.execute('SELECT * FROM tasty_words')
    words = await cursur.fetchall()
    words_list = []
    for w in words:
        words_list.append(w[1])

    if len(words_list) == 0:
        await ctx.send("残念ながら食べ物がありません..")
        return

    await ctx.send(embed=discord.Embed(title="お腹すいた！", description=f"{random.choice(words_list)}とかどう？", color=discord.Color.yellow()))

bot.run(os.environ.get('DISCORD_TOKEN'))