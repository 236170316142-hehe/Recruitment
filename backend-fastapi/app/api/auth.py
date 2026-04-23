"""
Authentication and user management routes
"""

import logging
from fastapi import APIRouter, HTTPException, status, Depends, Request
from datetime import timedelta

from app.models.user import (
    GoogleSignInRequest,
    GoogleSignInResponse,
    EmailSignInRequest,
    GmailConnectRequest,
    GmailConnectResponse,
    UserProfileResponse,
    LogoutResponse,
)
from app.services.google_oauth import GoogleOAuthService
from app.services.user_service import UserService
from app.core.auth import create_jwt_token, get_current_user, verify_jwt_token
from app.db.mongo import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/email/signin", response_model=GoogleSignInResponse)
async def email_signin(request: EmailSignInRequest, db=Depends(get_db)):
    """Email-only development sign-in when Google OAuth is unavailable."""
    try:
        user_service = UserService(db)
        user = await user_service.create_or_update_email_user(
            email=request.email,
            name=request.name,
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create local user",
            )

        session_token = create_jwt_token(
            {
                "user_id": user["user_id"],
                "email": user["email"],
                "name": user["name"],
            }
        )

        connected_accounts = await user_service.get_user_connected_gmail_accounts(user["user_id"])

        return GoogleSignInResponse(
            user_id=user["user_id"],
            email=user["email"],
            name=user["name"],
            picture_url=user.get("picture_url"),
            session_token=session_token,
            connected_gmail_accounts=connected_accounts,
            active_gmail_account=user.get("active_gmail_account_email"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in email sign-in: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email sign-in failed",
        )


@router.post("/google/signin", response_model=GoogleSignInResponse)
async def google_signin(request: GoogleSignInRequest, db=Depends(get_db)):
    """
    Google Sign-In endpoint
    Frontend sends ID token from Google Identity Services
    Backend verifies token and creates/updates user
    """
    try:
        # Verify the ID token with Google
        user_info = await GoogleOAuthService.verify_id_token(request.id_token)
        if not user_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token"
            )
        
        # Create or update user in database
        user_service = UserService(db)
        user = await user_service.create_or_update_user(
            google_id=user_info["google_id"],
            email=user_info["email"],
            name=user_info["name"],
            picture_url=user_info.get("picture_url")
        )
        
        # Create JWT session token
        session_token = create_jwt_token({
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
        })
        
        # Get connected Gmail accounts
        connected_accounts = await user_service.get_user_connected_gmail_accounts(user["user_id"])
        
        return GoogleSignInResponse(
            user_id=user["user_id"],
            email=user["email"],
            name=user["name"],
            picture_url=user.get("picture_url"),
            session_token=session_token,
            connected_gmail_accounts=connected_accounts,
            active_gmail_account=user.get("active_gmail_account_email"),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Google sign-in: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sign-in failed"
        )


@router.post("/google/signin-unified", response_model=GoogleSignInResponse)
async def google_signin_unified(request: GmailConnectRequest, db=Depends(get_db)):
    """
    Unified Login & Gmail Connect endpoint
    Frontend sends authorization code obtained from custom Google button
    """
    try:
        # 1. Exchange code for tokens (includes profile and gmail.readonly)
        # For popups (initCodeClient), the redirect_uri must be "postmessage"
        tokens = await GoogleOAuthService.exchange_auth_code_for_tokens(
            request.auth_code, 
            redirect_uri="postmessage"
        )
        if not tokens or not tokens.get("user_info"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code or fetch user info"
            )
        
        user_info = tokens["user_info"]
        
        # 2. Create or update user
        user_service = UserService(db)
        user = await user_service.create_or_update_user(
            google_id=user_info["google_id"],
            email=user_info["email"],
            name=user_info["name"],
            picture_url=user_info.get("picture_url")
        )
        
        # 3. Automatically connect the Gmail account used for login
        await user_service.add_connected_gmail_account(
            user_id=user["user_id"],
            gmail_email=user_info["email"],
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_at=tokens["expires_at"],
            scopes=GoogleOAuthService.GMAIL_SCOPES
        )
        
        # 4. Set it as active
        await user_service.set_active_gmail_account(user["user_id"], user_info["email"])
        
        # 5. Create JWT session token
        session_token = create_jwt_token({
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
        })
        
        connected_accounts = await user_service.get_user_connected_gmail_accounts(user["user_id"])
        
        return GoogleSignInResponse(
            user_id=user["user_id"],
            email=user["email"],
            name=user["name"],
            picture_url=user.get("picture_url"),
            session_token=session_token,
            connected_gmail_accounts=connected_accounts,
            active_gmail_account=user_info["email"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in unified sign-in: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unified sign-in failed"
        )


@router.get("/google/gmail-connect-url")
async def get_gmail_connect_url(current_user: dict = Depends(get_current_user)):
    """
    Get Google OAuth URL for connecting Gmail account
    User clicks this link → redirected to Google OAuth consent screen
    """
    try:
        # Generate state parameter to prevent CSRF
        # In production, store in Redis/database
        state = current_user["user_id"]
        
        url = GoogleOAuthService.get_gmail_oauth_url(state=state)
        return {"oauth_url": url}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Gmail connect URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL"
        )


@router.post("/google/gmail-callback")
async def gmail_callback(request: GmailConnectRequest, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    OAuth callback handler for Gmail connection
    Called after user approves consent on Google's screen
    Exchange auth_code for refresh/access tokens
    """
    try:
        # Exchange auth code for tokens
        # Try primary redirect URI first
        tokens = await GoogleOAuthService.exchange_auth_code_for_tokens(request.auth_code)
        
        # If that fails, it might be a popup flow needing "postmessage"
        if not tokens:
            tokens = await GoogleOAuthService.exchange_auth_code_for_tokens(
                request.auth_code, 
                redirect_uri="postmessage"
            )
            
        if not tokens:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code"
            )
        
        # Add connected Gmail account to user
        user_service = UserService(db)
        updated_user = await user_service.add_connected_gmail_account(
            user_id=current_user["user_id"],
            gmail_email=tokens["email"],
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_at=tokens["expires_at"],
            scopes=GoogleOAuthService.GMAIL_SCOPES
        )
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return GmailConnectResponse(
            email=tokens["email"],
            scopes=GoogleOAuthService.GMAIL_SCOPES,
            connected_at=updated_user.get("created_at"),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Gmail callback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Gmail account"
        )


@router.post("/gmail/disconnect/{gmail_email}")
async def disconnect_gmail(gmail_email: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Disconnect a Gmail account from the user
    """
    try:
        user_service = UserService(db)
        result = await user_service.disconnect_gmail_account(
            user_id=current_user["user_id"],
            gmail_email=gmail_email
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gmail account not found"
            )
        
        return {"message": f"Gmail account {gmail_email} disconnected"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting Gmail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect Gmail account"
        )


@router.post("/gmail/set-active/{gmail_email}")
async def set_active_gmail(gmail_email: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Set which Gmail account to use for resume fetching
    """
    try:
        user_service = UserService(db)
        result = await user_service.set_active_gmail_account(
            user_id=current_user["user_id"],
            gmail_email=gmail_email
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gmail account not found"
            )
        
        return {"message": f"Active Gmail account set to {gmail_email}"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting active Gmail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set active Gmail account"
        )


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Get current user profile including connected Gmail accounts
    """
    try:
        user_service = UserService(db)
        user = await user_service.get_user_by_id(current_user["user_id"])
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        connected_accounts = await user_service.get_user_connected_gmail_accounts(user["user_id"])
        
        return UserProfileResponse(
            user_id=user["user_id"],
            email=user["email"],
            name=user["name"],
            picture_url=user.get("picture_url"),
            connected_gmail_accounts=connected_accounts,
            active_gmail_account=user.get("active_gmail_account_email"),
            last_login=user.get("last_login"),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch profile"
        )


@router.post("/logout", response_model=LogoutResponse)
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Logout endpoint (mostly for frontend to notify backend)
    Frontend should clear JWT token from localStorage
    """
    return LogoutResponse(message="Successfully logged out")


@router.get("/verify-token")
async def verify_token(current_user: dict = Depends(get_current_user)):
    """
    Verify if current JWT token is valid
    Used by frontend to check if session is still active
    """
    return {
        "valid": True,
        "user_id": current_user.get("user_id"),
        "email": current_user.get("email"),
        "name": current_user.get("name"),
    }
