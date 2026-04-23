from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings


class MongoConnection:
    client: AsyncIOMotorClient | None = None


mongo = MongoConnection()


def get_client() -> AsyncIOMotorClient:
    if mongo.client is None:
        mongo.client = AsyncIOMotorClient(settings.mongo_uri)
    return mongo.client


def get_db():
    return get_client()[settings.mongo_db_name]


async def close_client() -> None:
    if mongo.client is not None:
        mongo.client.close()
        mongo.client = None
