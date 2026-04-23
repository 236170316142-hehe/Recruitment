"""
User and authentication models for Pydantic validation
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum


class GmailScope(str, Enum):
    """Gmail API scopes"""
    READONLY = "https://www.googleapis.com/auth/gmail.readonly"
    MODIFY = "https://www.googleapis.com/auth/gmail.modify"


class ConnectedGmailAccount(BaseModel):
    """Gmail account connected to a user"""
    email: str  # Gmail address
    refresh_token: str  # OAuth refresh token (encrypted)
    access_token: Optional[str] = None  # Current access token
    token_expiry: Optional[datetime] = None
    scopes: List[GmailScope] = [GmailScope.READONLY]
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    is_active: bool = True


class HRUser(BaseModel):
    """HR user account with Google OAuth"""
    user_id: str  # UUID
    google_id: str  # Google's unique ID
    email: EmailStr  # HR's Google email
    name: str
    picture_url: Optional[str] = None
    
    # Connected Gmail accounts per user
    connected_gmail_accounts: List[ConnectedGmailAccount] = []
    active_gmail_account_email: Optional[str] = None  # Which Gmail account is active
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    is_active: bool = True


# ============================================================================
# Request/Response Models
# ============================================================================

class GoogleSignInRequest(BaseModel):
    """Google ID token from frontend"""
    id_token: str


class EmailSignInRequest(BaseModel):
    """Email-only dev sign-in request"""
    email: EmailStr
    name: Optional[str] = None


class GoogleSignInResponse(BaseModel):
    """Response after Google sign-in"""
    user_id: str
    email: str
    name: str
    picture_url: Optional[str]
    session_token: str  # JWT for session management
    connected_gmail_accounts: List[str] = []  # List of connected Gmail addresses
    active_gmail_account: Optional[str] = None


class GmailConnectRequest(BaseModel):
    """Request to connect a Gmail account"""
    auth_code: str  # Authorization code from Google OAuth


class GmailConnectResponse(BaseModel):
    """Response after Gmail connection"""
    email: str
    scopes: List[str]
    connected_at: datetime


class UserProfileResponse(BaseModel):
    """User profile data"""
    user_id: str
    email: str
    name: str
    picture_url: Optional[str]
    connected_gmail_accounts: List[str]
    active_gmail_account: Optional[str]
    last_login: Optional[datetime]


class LogoutResponse(BaseModel):
    """Logout response"""
    message: str = "Successfully logged out"
