from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
import requests

from app.db.database import get_session
from app.models.entities import ConnectedAccount, ConnectorState
from app.schemas.connectors import ConnectedAccountResponse, ConnectorCallbackResponse

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])

YOUTUBE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CONNECTOR_STATE_TTL_MINUTES = 15


def _youtube_redirect_uri() -> str:
    redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI")
    if redirect_uri:
        return redirect_uri

    api_base_url = os.getenv("PUBLIC_API_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{api_base_url}/v1/connectors/youtube/callback"


def _require_youtube_app_config() -> tuple[str, str, str]:
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    redirect_uri = _youtube_redirect_uri()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are required to connect YouTube accounts",
        )
    return client_id, client_secret, redirect_uri


@router.get("", response_model=list[ConnectedAccountResponse], summary="List connected upload accounts")
def list_connected_accounts(
    platform: str | None = Query(default=None, min_length=2, max_length=32),
    session: Session = Depends(get_session),
):
    query = select(ConnectedAccount)
    if platform:
        query = query.where(ConnectedAccount.platform == platform.strip().lower())
    return session.exec(query.order_by(ConnectedAccount.created_at.desc())).all()


@router.get("/youtube/authorize", summary="Start the YouTube upload connector OAuth flow")
def authorize_youtube(
    redirect_after: str | None = Query(default=None, max_length=2048),
    session: Session = Depends(get_session),
):
    client_id, _client_secret, redirect_uri = _require_youtube_app_config()
    state_value = token_urlsafe(32)
    session.add(
        ConnectorState(
            platform="youtube",
            state=state_value,
            redirect_after=redirect_after,
        )
    )
    session.commit()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": YOUTUBE_UPLOAD_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state_value,
    }
    return RedirectResponse(f"{YOUTUBE_AUTH_URL}?{urlencode(params)}")


@router.get(
    "/youtube/callback",
    response_model=ConnectorCallbackResponse,
    summary="Complete the YouTube upload connector OAuth flow",
)
def youtube_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
):
    if error:
        raise HTTPException(status_code=400, detail=f"YouTube authorization failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="YouTube callback requires code and state")

    connector_state = session.exec(
        select(ConnectorState).where(
            ConnectorState.platform == "youtube",
            ConnectorState.state == state,
            ConnectorState.consumed_at.is_(None),
        )
    ).first()
    if not connector_state:
        raise HTTPException(status_code=400, detail="Invalid or already used connector state")
    if connector_state.created_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - timedelta(
        minutes=CONNECTOR_STATE_TTL_MINUTES
    ):
        raise HTTPException(status_code=400, detail="Connector state expired; please connect YouTube again")

    client_id, client_secret, redirect_uri = _require_youtube_app_config()
    token_data = _exchange_youtube_code(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    connected_account = _store_youtube_connected_account(session, token_data)
    connector_state.consumed_at = datetime.utcnow()
    session.add(connector_state)
    session.commit()
    session.refresh(connected_account)

    if connector_state.redirect_after:
        separator = "&" if "?" in connector_state.redirect_after else "?"
        return RedirectResponse(
            f"{connector_state.redirect_after}{separator}youtube_connected={connected_account.id}"
        )

    return {"connected_account": connected_account, "status": "connected"}


@router.delete("/{connected_account_id}", status_code=204, summary="Remove a connected upload account")
def delete_connected_account(connected_account_id: int, session: Session = Depends(get_session)):
    connected_account = session.get(ConnectedAccount, connected_account_id)
    if not connected_account:
        raise HTTPException(status_code=404, detail="Connected account not found")
    session.delete(connected_account)
    session.commit()


def _exchange_youtube_code(*, code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    try:
        response = requests.post(
            os.getenv("YOUTUBE_TOKEN_URI", YOUTUBE_TOKEN_URL),
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"YouTube token exchange failed: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=400,
            detail=f"YouTube token exchange failed with HTTP {response.status_code}: {response.text[:512]}",
        )

    token_data = response.json()
    if not isinstance(token_data, dict) or not token_data.get("access_token"):
        raise HTTPException(status_code=400, detail="YouTube token response did not include an access token")
    return token_data


def _store_youtube_connected_account(session: Session, token_data: dict[str, Any]) -> ConnectedAccount:
    now = datetime.utcnow()
    expires_in = token_data.get("expires_in")
    expires_at = None
    if isinstance(expires_in, int):
        expires_at = now + timedelta(seconds=expires_in)

    connected_account = ConnectedAccount(
        platform="youtube",
        provider_account_id=f"youtube-{int(now.timestamp())}",
        display_name="YouTube connected account",
        access_token=str(token_data["access_token"]),
        refresh_token=token_data.get("refresh_token"),
        token_type=str(token_data.get("token_type") or "Bearer"),
        scopes=str(token_data.get("scope") or YOUTUBE_UPLOAD_SCOPE),
        expires_at=expires_at,
        updated_at=now,
    )
    session.add(connected_account)
    session.commit()
    session.refresh(connected_account)
    return connected_account
