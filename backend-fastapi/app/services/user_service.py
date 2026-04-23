"""
User management service for HR users and Gmail accounts
"""

import uuid
from datetime import datetime
from typing import Optional, List
import logging
from bson import ObjectId

logger = logging.getLogger(__name__)


class UserService:
    """Manages HR users and their connected Gmail accounts"""
    
    def __init__(self, db):
        self.db = db
        self.users_collection = db.users  # HR users collection
    
    async def create_or_update_user(
        self,
        google_id: str,
        email: str,
        name: str,
        picture_url: Optional[str] = None
    ):
        """
        Create or update an HR user after Google sign-in
        Returns the full user document
        """
        user_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        result = await self.users_collection.find_one_and_update(
            {"google_id": google_id},
            {
                "$set": {
                    "email": email,
                    "name": name,
                    "picture_url": picture_url,
                    "last_login": now,
                    "is_active": True,
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "google_id": google_id,
                    "connected_gmail_accounts": [],
                    "active_gmail_account_email": None,
                    "created_at": now,
                }
            },
            upsert=True,
            return_document=True
        )
        
        return result

    async def create_or_update_email_user(
        self,
        email: str,
        name: Optional[str] = None,
        picture_url: Optional[str] = None,
    ):
        """Create or update a local email-only user for development access."""
        local_user_id = f"local-{email.lower()}"
        now = datetime.utcnow()

        result = await self.users_collection.find_one_and_update(
            {"email": email},
            {
                "$set": {
                    "email": email,
                    "name": name or email.split("@")[0],
                    "picture_url": picture_url,
                    "last_login": now,
                    "is_active": True,
                    "google_id": local_user_id,
                },
                "$setOnInsert": {
                    "user_id": str(uuid.uuid4()),
                    "connected_gmail_accounts": [],
                    "active_gmail_account_email": None,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=True,
        )

        return result
    
    async def get_user_by_id(self, user_id: str):
        """Get user by user_id"""
        return await self.users_collection.find_one({"user_id": user_id})
    
    async def get_user_by_google_id(self, google_id: str):
        """Get user by google_id"""
        return await self.users_collection.find_one({"google_id": google_id})
    
    async def add_connected_gmail_account(
        self,
        user_id: str,
        gmail_email: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        scopes: List[str]
    ):
        """
        Add a connected Gmail account to the user
        Each user can have multiple connected accounts
        """
        gmail_account = {
            "email": gmail_email,
            "refresh_token": refresh_token,
            "access_token": access_token,
            "token_expiry": expires_at,
            "scopes": scopes,
            "connected_at": datetime.utcnow(),
            "last_used": None,
            "is_active": True,
        }
        
        # Check if this Gmail account is already connected
        user = await self.get_user_by_id(user_id)
        if user:
            existing_accounts = user.get("connected_gmail_accounts", [])
            # Remove old entry if exists
            existing_accounts = [a for a in existing_accounts if a.get("email") != gmail_email]
            existing_accounts.append(gmail_account)
            
            # If no active account, set this as active
            if not user.get("active_gmail_account_email"):
                active_email = gmail_email
            else:
                active_email = user.get("active_gmail_account_email")
            
            result = await self.users_collection.find_one_and_update(
                {"user_id": user_id},
                {
                    "$set": {
                        "connected_gmail_accounts": existing_accounts,
                        "active_gmail_account_email": active_email,
                    }
                },
                return_document=True
            )
            return result
        return None
    
    async def set_active_gmail_account(self, user_id: str, gmail_email: str):
        """Set which Gmail account is active for this user"""
        user = await self.get_user_by_id(user_id)
        if user:
            accounts = user.get("connected_gmail_accounts", [])
            # Verify the account exists
            if any(a.get("email") == gmail_email for a in accounts):
                result = await self.users_collection.find_one_and_update(
                    {"user_id": user_id},
                    {"$set": {"active_gmail_account_email": gmail_email}},
                    return_document=True
                )
                return result
        return None
    
    async def get_active_gmail_token(self, user_id: str) -> Optional[str]:
        """
        Get the access token for the user's active Gmail account
        Refreshes token if expired
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        
        active_email = user.get("active_gmail_account_email")
        if not active_email:
            return None
        
        # Find the active account
        accounts = user.get("connected_gmail_accounts", [])
        active_account = next((a for a in accounts if a.get("email") == active_email), None)
        
        if not active_account:
            return None
        
        # Check if token expired
        from app.services.google_oauth import GoogleOAuthService
        expiry = active_account.get("token_expiry")
        
        if GoogleOAuthService.is_token_expired(expiry):
            # Refresh token
            refresh_token = active_account.get("refresh_token")
            new_tokens = await GoogleOAuthService.refresh_access_token(refresh_token)
            
            if new_tokens:
                # Update the account with new token
                updated_accounts = []
                for acc in accounts:
                    if acc.get("email") == active_email:
                        acc["access_token"] = new_tokens["access_token"]
                        acc["token_expiry"] = new_tokens["expires_at"]
                    updated_accounts.append(acc)
                
                await self.users_collection.find_one_and_update(
                    {"user_id": user_id},
                    {"$set": {"connected_gmail_accounts": updated_accounts}},
                    return_document=True
                )
                
                return new_tokens["access_token"]
        
        # Token still valid
        return active_account.get("access_token")
    
    async def disconnect_gmail_account(self, user_id: str, gmail_email: str):
        """Remove a connected Gmail account"""
        user = await self.get_user_by_id(user_id)
        if user:
            accounts = user.get("connected_gmail_accounts", [])
            accounts = [a for a in accounts if a.get("email") != gmail_email]
            
            # If this was the active account, set a new one
            active_email = user.get("active_gmail_account_email")
            new_active = accounts[0].get("email") if accounts else None
            if active_email == gmail_email:
                active_email = new_active
            
            result = await self.users_collection.find_one_and_update(
                {"user_id": user_id},
                {
                    "$set": {
                        "connected_gmail_accounts": accounts,
                        "active_gmail_account_email": active_email,
                    }
                },
                return_document=True
            )
            return result
        return None
    
    async def get_user_connected_gmail_accounts(self, user_id: str) -> List[str]:
        """Get list of connected Gmail account emails for a user"""
        user = await self.get_user_by_id(user_id)
        if user:
            accounts = user.get("connected_gmail_accounts", [])
            return [a.get("email") for a in accounts if a.get("email")]
        return []
