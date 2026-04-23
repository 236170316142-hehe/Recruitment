"""
Google OAuth service for HR authentication and Gmail account management
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.rfc7662 import IntrospectionToken
import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class GoogleOAuthService:
    """Handles Google OAuth sign-in and Gmail account connections"""
    
    # Gmail API
    GMAIL_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        # "https://www.googleapis.com/auth/gmail.modify",  # Optional, enable if needed
    ]
    
    @staticmethod
    async def verify_id_token(id_token_str: str) -> Optional[Dict[str, Any]]:
        """
        Verify Google ID token and extract user info
        Called during sign-in with Google Sign-In button
        """
        try:
            # Verify the token with Google's public keys
            idinfo = id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                settings.google_client_id,
                clock_skew_in_seconds=10
            )
            
            # Token valid; extract user info
            return {
                "google_id": idinfo.get("sub"),
                "email": idinfo.get("email"),
                "name": idinfo.get("name"),
                "picture_url": idinfo.get("picture"),
                "email_verified": idinfo.get("email_verified", False)
            }
        except ValueError as e:
            logger.error(f"Invalid ID token: {e}")
            return None
    
    @staticmethod
    def get_gmail_oauth_url(state: str = "") -> str:
        """
        Generate Google OAuth URL for connecting Gmail account
        HR clicks "Connect Gmail" → redirected to this URL
        """
        base_url = "https://accounts.google.com/o/oauth2/v2/auth"
        scopes = " ".join(GoogleOAuthService.GMAIL_SCOPES)
        
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "access_type": "offline",  # Request refresh token
            "prompt": "consent",  # Force consent even if authorized before
            "state": state,
        }
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{query_string}"
    
    @staticmethod
    async def exchange_auth_code_for_tokens(auth_code: str, redirect_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for access and refresh tokens
        Called with auth_code from OAuth callback
        """
        try:
            url = "https://oauth2.googleapis.com/token"
            
            data = {
                "code": auth_code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri or settings.google_redirect_uri,
                "grant_type": "authorization_code"
            }
            
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data)
                response.raise_for_status()
                tokens = response.json()
            
            # Get user info from access token
            user_info = await GoogleOAuthService.get_user_info_from_token(tokens["access_token"])
            
            return {
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "expires_at": datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600)),
                "user_info": user_info,
            }
        except Exception as e:
            logger.error(f"Error exchanging auth code: {e}")
            return None
    
    @staticmethod
    async def get_user_info_from_token(access_token: str) -> Optional[Dict[str, Any]]:
        """Extract user profile info from access token using Google UserInfo API"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "google_id": data.get("sub"),
                    "email": data.get("email"),
                    "name": data.get("name"),
                    "picture_url": data.get("picture"),
                }
        except Exception as e:
            logger.error(f"Error getting user info from token: {e}")
            return None
    
    @staticmethod
    async def refresh_access_token(refresh_token: str) -> Optional[Dict[str, Any]]:
        """
        Refresh an expired access token using refresh token
        Called before using the token to ensure it's still valid
        """
        try:
            url = "https://oauth2.googleapis.com/token"
            
            data = {
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token"
            }
            
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data)
                response.raise_for_status()
                tokens = response.json()
            
            return {
                "access_token": tokens.get("access_token"),
                "expires_at": datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600)),
            }
        except Exception as e:
            logger.error(f"Error refreshing access token: {e}")
            return None
    
    @staticmethod
    def is_token_expired(expiry: Optional[datetime]) -> bool:
        """Check if token has expired (with 5-min buffer)"""
        if not expiry:
            return True
        return datetime.utcnow() >= (expiry - timedelta(minutes=5))
