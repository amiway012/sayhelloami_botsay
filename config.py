import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMINS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
