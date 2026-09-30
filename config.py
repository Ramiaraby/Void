from bot.bot import Bot

prefix = '!'
bot_name = 'Void'

with open("gitignore/bot token.txt", "r", encoding="utf-8") as f:
    bot_token = f.read().strip()

bot = Bot(prefix='!')