import hashlib
import json
import time

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .models import User

_fb_app = None
_token_cache: dict[str, tuple[float, dict]] = {}
_TTL = 300


def init_firebase():
    global _fb_app
    if _fb_app is not None:
        return
    if not (config.settings.firebase_sa_json or config.settings.firebase_sa_path):
        return
    import firebase_admin
    from firebase_admin import credentials

    if config.settings.firebase_sa_json:
        cred = credentials.Certificate(json.loads(config.settings.firebase_sa_json))
    else:
        cred = credentials.Certificate(config.settings.firebase_sa_path)
    _fb_app = firebase_admin.initialize_app(cred)


def _verify_firebase(token: str) -> dict:
    init_firebase()
    if _fb_app is None:
        raise RuntimeError(
            "Firebase Admin not configured. Set FIREBASE_SERVICE_ACCOUNT_JSON "
            "(or GOOGLE_APPLICATION_CREDENTIALS), or enable DEV_AUTH=1."
        )
    from firebase_admin import auth as fb_auth

    return fb_auth.verify_id_token(token, clock_skew_seconds=60)


def verify_token(token: str) -> dict:
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    cached = _token_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    claims = _verify_firebase(token)
    _token_cache[key] = (now + _TTL, claims)
    if len(_token_cache) > 5000:
        _token_cache.clear()
    return claims


def claims_from_request(request: Request) -> dict:
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        try:
            return verify_token(authz[7:].strip())
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    if config.settings.dev_auth:
        uid = request.headers.get("x-dev-uid")
        if uid:
            return {
                "uid": uid,
                "email": f"{uid}@dev.local",
                "name": request.headers.get("x-dev-name", uid),
            }
    raise HTTPException(status_code=401, detail="Missing Authorization bearer token")


def claims_from_ws(token: str | None, uid_override: str | None, name: str | None) -> dict:
    if uid_override and config.settings.dev_auth:
        return {"uid": uid_override, "email": f"{uid_override}@dev.local", "name": name or uid_override}
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        return verify_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


def upsert_user(db: Session, claims: dict) -> User:
    uid = claims["uid"]
    user = db.get(User, uid)
    if user is None:
        user = User(id=uid)
        db.add(user)
    user.email = claims.get("email") or user.email or ""
    user.display_name = claims.get("name") or user.display_name or uid
    if config.settings.dev_auth and uid in config.settings.admin_uids:
        user.is_admin = True
    elif "admin" in claims:
        user.is_admin = bool(claims["admin"])
    photo = claims.get("picture") or claims.get("photo_url") or ""
    if photo:
        user.photo_url = photo
    db.commit()
    db.refresh(user)
    return user
