import os
import base64
from datetime import datetime, timezone
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailClient:
    def __init__(self, credentials_json: Optional[str] = None):
        self.credentials = None
        self.service = None
        self.credentials_json = credentials_json or os.getenv("GOOGLE_CREDENTIALS_JSON")

    @classmethod
    def from_access_token(cls, access_token: str):
        instance = cls()
        instance.credentials = Credentials(token=access_token)
        instance.service = build("gmail", "v1", credentials=instance.credentials)
        return instance

    def authenticate(self) -> bool:
        if not self.credentials_json:
            return False

        try:
            creds_dict = eval(self.credentials_json)
            if "type" in creds_dict and creds_dict["type"] == "service_account":
                self.credentials = ServiceAccountCredentials.from_service_account_info(creds_dict, scopes=SCOPES)
            else:
                self.credentials = Credentials.from_authorized_user_info(creds_dict, scopes=SCOPES)
            
            self.service = build("gmail", "v1", credentials=self.credentials)
            return True
        except Exception as e:
            print(f"Gmail auth failed: {e}")
            return False

    def fetch_attachments(self, query: str = "has:attachment filename:(pdf OR docx OR txt)") -> list[dict]:
        if not self.service:
            print("Gmail service not initialized")
            return []

        try:
            print(f"Searching Gmail with query: {query}")
            results = self.service.users().messages().list(userId="me", q=query, maxResults=20).execute()
            messages = results.get("messages", [])
            attachments = []

            for msg in messages:
                msg_data = self.service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
                headers = msg_data["payload"].get("headers", [])
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "Unknown")
                sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")

                # Recursive extraction function
                def extract_parts(parts):
                    for part in parts:
                        if part.get("parts"):
                            extract_parts(part["parts"])
                        
                        filename = part.get("filename")
                        if filename and any(filename.lower().endswith(ext) for ext in [".pdf", ".docx", ".txt"]):
                            attachment_id = part["body"].get("attachmentId")
                            if attachment_id:
                                try:
                                    att = self.service.users().messages().attachments().get(
                                        userId="me", messageId=msg["id"], id=attachment_id
                                    ).execute()
                                    file_data = base64.urlsafe_b64decode(att["data"])
                                    attachments.append({
                                        "filename": filename,
                                        "data": file_data,
                                        "sender": sender,
                                        "subject": subject,
                                        "received_at": datetime.now(timezone.utc),
                                    })
                                    print(f"Found attachment: {filename} in '{subject}'")
                                except Exception as e:
                                    print(f"Error downloading attachment {filename}: {e}")

                # Initial call to extraction
                payload = msg_data.get("payload", {})
                if "parts" in payload:
                    extract_parts(payload["parts"])
                elif payload.get("filename"): # Single part attachment
                    extract_parts([payload])

            print(f"Successfully fetched {len(attachments)} attachments total.")
            return attachments
        except Exception as e:
            print(f"Error in fetch_attachments: {e}")
            return []
