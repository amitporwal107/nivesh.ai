"""Repository layer — all MongoDB operations abstracted."""
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional
from datetime import datetime, timezone, timedelta
import uuid


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def find_by_email(self, email: str) -> Optional[dict]:
        return await self.db.users.find_one({"email": email}, {"_id": 0})

    async def find_by_id(self, user_id: str) -> Optional[dict]:
        return await self.db.users.find_one({"user_id": user_id}, {"_id": 0})

    async def upsert(self, email: str, name: str, picture: str) -> dict:
        existing = await self.find_by_email(email)
        if existing:
            await self.db.users.update_one({"email": email}, {"$set": {"name": name, "picture": picture}})
            return await self.find_by_email(email)
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        doc = {"user_id": user_id, "email": email, "name": name, "picture": picture, "created_at": datetime.now(timezone.utc).isoformat()}
        await self.db.users.insert_one(doc)
        return await self.find_by_id(user_id)


class SessionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create(self, user_id: str, token: str, ttl_days: int = 7) -> None:
        await self.db.user_sessions.insert_one({
            "user_id": user_id,
            "session_token": token,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
        })

    async def validate(self, token: str) -> Optional[dict]:
        session = await self.db.user_sessions.find_one({"session_token": token}, {"_id": 0})
        if not session:
            return None
        expires = session["expires_at"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            await self.db.user_sessions.delete_one({"session_token": token})
            return None
        # Refresh last_active (extends session feel)
        await self.db.user_sessions.update_one(
            {"session_token": token},
            {"$set": {"last_active": datetime.now(timezone.utc).isoformat()}}
        )
        return session

    async def delete_token(self, token: str) -> None:
        await self.db.user_sessions.delete_many({"session_token": token})

    async def delete_all_for_user(self, user_id: str) -> int:
        result = await self.db.user_sessions.delete_many({"user_id": user_id})
        return result.deleted_count

    async def cleanup_expired(self) -> int:
        result = await self.db.user_sessions.delete_many({
            "expires_at": {"$lt": datetime.now(timezone.utc).isoformat()}
        })
        return result.deleted_count


class PortfolioRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create(self, user_id: str, name: str, member_name: str, relationship: str) -> dict:
        doc = {
            "portfolio_id": f"pf_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "name": name,
            "member_name": member_name,
            "relationship": relationship,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.portfolios.insert_one(doc)
        return await self.db.portfolios.find_one({"portfolio_id": doc["portfolio_id"]}, {"_id": 0})

    async def list_for_user(self, user_id: str) -> list:
        portfolios = await self.db.portfolios.find({"user_id": user_id}, {"_id": 0}).to_list(50)
        for p in portfolios:
            p["holdings_count"] = await self.db.holdings.count_documents({"user_id": user_id, "portfolio_id": p["portfolio_id"]})
        return portfolios

    async def delete(self, user_id: str, portfolio_id: str) -> int:
        result = await self.db.portfolios.delete_one({"portfolio_id": portfolio_id, "user_id": user_id})
        if result.deleted_count:
            del_result = await self.db.holdings.delete_many({"user_id": user_id, "portfolio_id": portfolio_id})
            return del_result.deleted_count
        return 0


class HoldingRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create(self, holding_data: dict) -> dict:
        holding_data["holding_id"] = f"hold_{uuid.uuid4().hex[:12]}"
        holding_data["created_at"] = datetime.now(timezone.utc).isoformat()
        await self.db.holdings.insert_one(holding_data)
        return await self.db.holdings.find_one({"holding_id": holding_data["holding_id"]}, {"_id": 0})

    async def find_for_user(self, user_id: str, portfolio_id: str = "", asset_type: str = "") -> list:
        query = {"user_id": user_id}
        if portfolio_id:
            query["portfolio_id"] = portfolio_id
        if asset_type:
            query["asset_type"] = asset_type
        return await self.db.holdings.find(query, {"_id": 0}).to_list(2000)

    async def update(self, user_id: str, holding_id: str, data: dict) -> Optional[dict]:
        await self.db.holdings.update_one({"holding_id": holding_id, "user_id": user_id}, {"$set": data})
        return await self.db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})

    async def delete(self, user_id: str, holding_id: str) -> bool:
        result = await self.db.holdings.delete_one({"holding_id": holding_id, "user_id": user_id})
        return result.deleted_count > 0

    async def bulk_insert(self, holdings: list) -> int:
        if not holdings:
            return 0
        for h in holdings:
            h["holding_id"] = f"hold_{uuid.uuid4().hex[:12]}"
            h["created_at"] = datetime.now(timezone.utc).isoformat()
        await self.db.holdings.insert_many(holdings)
        return len(holdings)
