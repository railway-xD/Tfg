import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "tfg_cricket_rivalry").strip()
DEFAULT_GROUP_ID = os.getenv("DEFAULT_GROUP_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it to Railway Variables or .env")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is missing. Add your MongoDB connection string.")
