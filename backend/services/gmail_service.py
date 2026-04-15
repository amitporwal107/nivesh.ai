"""Gmail Auto-Fetch Service — connects user Gmail, scans for CAS emails,
extracts PDF attachments, and feeds them into the CAS parser."""
import logging
import base64
import warnings
from datetime import datetime, timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# CAS email detection patterns
CAS_SENDERS = [
    "nsdl", "cdsl", "cams", "kfintech", "karvy",
    "donotreply@camsonline.com", "donotreply@kfintech.com",
    "noreply@nsdl.co.in", "ecas@nsdl.co.in",
    "noreply@cdslindia.com", "edis@cdslindia.com",
]

CAS_SUBJECTS = [
    "consolidated account statement",
    "cas", "e-cas", "ecas",
    "account statement",
    "portfolio statement",
    "nsdl e-cas",
    "cdsl cas",
]


def create_gmail_flow(client_id: str, client_secret: str, redirect_uri: str) -> Flow:
    """Create Google OAuth flow for Gmail access."""
    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )


def get_authorization_url(client_id: str, client_secret: str, redirect_uri: str, state: str) -> str:
    """Generate Google OAuth authorization URL for Gmail."""
    flow = create_gmail_flow(client_id, client_secret, redirect_uri)
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
    )
    return url


def exchange_code_for_tokens(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    """Exchange authorization code for tokens."""
    flow = create_gmail_flow(client_id, client_secret, redirect_uri)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flow.fetch_token(code=code)

    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "expires_at": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
    }


def get_gmail_credentials(token_doc: dict) -> Credentials:
    """Build Credentials object from stored token, refreshing if needed."""
    creds = Credentials(
        token=token_doc["access_token"],
        refresh_token=token_doc.get("refresh_token"),
        token_uri=token_doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_doc["client_id"],
        client_secret=token_doc["client_secret"],
    )

    # Check expiry and refresh
    expires_at = token_doc.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            from dateutil.parser import parse as parse_date
            expires_at = parse_date(expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            try:
                creds.refresh(GoogleRequest())
                logger.info("Gmail token refreshed successfully")
            except Exception as e:
                logger.error(f"Gmail token refresh failed: {e}")
                raise

    return creds


def build_gmail_service(creds: Credentials):
    """Build Gmail API service."""
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def scan_for_cas_emails(service, max_results: int = 30) -> list:
    """Scan Gmail for CAS-related emails with PDF attachments.
    Returns list of email metadata with attachment info."""

    # Build search query
    sender_queries = " OR ".join([f"from:{s}" for s in CAS_SENDERS[:6]])
    subject_queries = " OR ".join([f'subject:"{s}"' for s in CAS_SUBJECTS[:4]])
    query = f"({sender_queries} OR {subject_queries}) has:attachment filename:pdf"

    logger.info(f"Gmail search query: {query}")

    try:
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
    except Exception as e:
        logger.error(f"Gmail search failed: {e}")
        return []

    messages = results.get("messages", [])
    if not messages:
        return []

    cas_emails = []
    for msg_meta in messages:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_meta["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            date = headers.get("date", "")

            # Check for PDF attachments
            attachments = _find_pdf_attachments(msg.get("payload", {}))
            if not attachments:
                continue

            # Score confidence
            confidence = _score_cas_confidence(sender, subject)

            cas_emails.append({
                "message_id": msg_meta["id"],
                "sender": sender,
                "subject": subject,
                "date": date,
                "attachments": attachments,
                "confidence": confidence,
            })
        except Exception as e:
            logger.warning(f"Failed to process email {msg_meta['id']}: {e}")

    # Sort by confidence then date
    cas_emails.sort(key=lambda x: x["confidence"], reverse=True)
    return cas_emails


def _find_pdf_attachments(payload: dict) -> list:
    """Recursively find PDF attachments in email payload."""
    attachments = []

    if payload.get("filename") and payload["filename"].lower().endswith(".pdf"):
        attach_id = payload.get("body", {}).get("attachmentId")
        if attach_id:
            attachments.append({
                "filename": payload["filename"],
                "attachment_id": attach_id,
                "size": payload.get("body", {}).get("size", 0),
            })

    for part in payload.get("parts", []):
        attachments.extend(_find_pdf_attachments(part))

    return attachments


def download_attachment(service, message_id: str, attachment_id: str) -> bytes:
    """Download a specific email attachment as bytes."""
    attachment = service.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()

    data = attachment.get("data", "")
    return base64.urlsafe_b64decode(data)


def _score_cas_confidence(sender: str, subject: str) -> float:
    """Score how likely an email is a CAS statement (0.0 - 1.0)."""
    score = 0.0
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    # Sender matching
    for s in CAS_SENDERS:
        if s in sender_lower:
            score += 0.4
            break

    # Subject matching
    for kw in CAS_SUBJECTS:
        if kw in subject_lower:
            score += 0.3
            break

    # Specific high-confidence patterns
    if "e-cas" in subject_lower or "ecas" in subject_lower:
        score += 0.2
    if "nsdl" in sender_lower or "cdsl" in sender_lower:
        score += 0.1

    return min(round(score, 2), 1.0)
