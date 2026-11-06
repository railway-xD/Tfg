from pymongo import AsyncMongoClient, ASCENDING, DESCENDING
from bot.config import MONGODB_URI, MONGODB_DATABASE

client = AsyncMongoClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=10000,
    tz_aware=True
)

database = client[MONGODB_DATABASE]
matches = database["matches"]
users = database["users"]

async def init_db():
    await client.admin.command("ping")
    await matches.create_index([("chat_id", ASCENDING), ("status", ASCENDING)])
    await matches.create_index([("chat_id", ASCENDING), ("created_at", DESCENDING)])
    await users.create_index([("user_id", ASCENDING)], unique=True)

async def close_db():
    await client.close()
