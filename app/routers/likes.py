"""Likes-tab endpoints (premium-gated "who liked me").

Mounted at prefix `/likes`. Implements the contract the iOS `LikesView`
already expects (see LIKES_TAB_PLAN.md for the as-built design decisions):

- GET  /likes/received       — grid of users who liked you; blurred for free
                               users until unlocked, unblurred for premium.
- POST /likes/unlock         — spend one of the day's free unlocks (premium =
                               unlimited) to reveal one liker's full profile.
- POST /likes/respond        — like/pass an (unlocked) liker; a like is always a
                               mutual match (they already liked you).
- GET  /likes/unlock-status  — small premium/quota probe (no iOS caller yet).

Premium gating policy (documented in LIKES_TAB_PLAN.md):
- "Premium" = users.is_premium AND (premium_expires_at IS NULL OR > now).
- Free tier: tiles blurred; ONE free unlock per UTC-day. Premium: unlimited +
  never blurred.
- Daily reset is UTC-midnight (backend UTC convention).
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import verify_firebase_token
from app.models import Match, PremiumUnlock, Swipe, User
from app.services import push_notification_service as push
from app.services.match_creation import create_match_in_firestore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/likes", tags=["likes"])

FREE_UNLOCKS_PER_DAY = 1


class UnlockRequest(BaseModel):
    firebase_uid_to_unlock: str


class RespondRequest(BaseModel):
    liked_user_firebase_uid: str
    action: str  # "like" | "pass"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_premium(user: User, now: datetime) -> bool:
    if not user.is_premium:
        return False
    exp = user.premium_expires_at
    if exp is None:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > now


def _utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _first_name(name: str | None) -> str | None:
    if not name:
        return None
    parts = name.split()
    return parts[0] if parts else None


def _representative_tag(user: User) -> str | None:
    """First interest as the tile's representative tag (mirrors the simple
    /matchmaking/likes/received tag)."""
    return user.interests[0] if user.interests else None


async def _resolve_self(db: AsyncSession, firebase_uid: str) -> User:
    user = (await db.execute(
        select(User).where(User.firebase_uid == firebase_uid)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _unlocks_used_today(db: AsyncSession, user_id: int, now: datetime) -> int:
    return (await db.execute(
        select(func.count(PremiumUnlock.id)).where(
            PremiumUnlock.user_id == user_id,
            PremiumUnlock.unlocked_at >= _utc_day_start(now),
        )
    )).scalar() or 0


async def _liker_swipe(db: AsyncSession, liker_id: int, me_id: int) -> Swipe | None:
    """The liker's right-swipe ON me (the reason they appear in my Likes)."""
    return (await db.execute(
        select(Swipe)
        .where(Swipe.swiper_id == liker_id)
        .where(Swipe.swiped_id == me_id)
        .where(Swipe.liked == True)  # noqa: E712
    )).scalar_one_or_none()


async def _already_responded(db: AsyncSession, me_id: int, target_id: int) -> bool:
    """True if I've already swiped on the target (responded to their like)."""
    return (await db.execute(
        select(Swipe.id)
        .where(Swipe.swiper_id == me_id)
        .where(Swipe.swiped_id == target_id)
    )).scalar_one_or_none() is not None


@router.get("/received")
async def get_received_likes(
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Users who liked the caller and haven't been responded to yet.

    Free users see blurred tiles (name/age/photo withheld → the client renders
    a blurred placeholder); premium users see full tiles. An individual liker a
    free user has already unlocked is returned unblurred.
    """
    now = _now()
    me = await _resolve_self(db, decoded_token["uid"])
    premium = _is_premium(me, now)

    # Likers who right-swiped me (most recent first).
    liker_swipes = (await db.execute(
        select(Swipe)
        .where(Swipe.swiped_id == me.id)
        .where(Swipe.liked == True)  # noqa: E712
        .order_by(Swipe.timestamp.desc())
    )).scalars().all()

    # Likers I've already responded to drop out of the pool.
    responded_ids = set((await db.execute(
        select(Swipe.swiped_id).where(Swipe.swiper_id == me.id)
    )).scalars().all())

    # Profiles this free user has already unlocked are shown unblurred.
    unlocked_ids = set((await db.execute(
        select(PremiumUnlock.unlocked_user_id).where(PremiumUnlock.user_id == me.id)
    )).scalars().all())

    has_used_unlock_today = (
        await _unlocks_used_today(db, me.id, now)
    ) >= FREE_UNLOCKS_PER_DAY

    profiles = []
    for sw in liker_swipes:
        if sw.swiper_id in responded_ids:
            continue
        liker = (await db.execute(
            select(User).where(User.id == sw.swiper_id, User.deleted_at.is_(None))
        )).scalar_one_or_none()
        if not liker:
            continue

        blurred = (not premium) and (liker.id not in unlocked_ids)
        liked_at = sw.timestamp.isoformat() if sw.timestamp else None

        if blurred:
            # Withhold identifying fields; the client shows "Someone" + a blurred
            # placeholder. Distance/tag are not surfaced for blurred tiles.
            profiles.append({
                "user_id": liker.id,
                "firebase_uid": liker.firebase_uid,
                "blurred": True,
                "photo_url": None,
                "first_name": None,
                "age": None,
                "compatibility_score": None,
                "city": None,
                "tag": None,
                "liked_at": liked_at,
            })
        else:
            profiles.append({
                "user_id": liker.id,
                "firebase_uid": liker.firebase_uid,
                "blurred": False,
                "photo_url": liker.profile_image_url,
                "first_name": _first_name(liker.name),
                "age": liker.age,
                # compatibility_score is optional; left null to avoid a
                # per-liker feature-vector load (LIKES_TAB_PLAN.md follow-up).
                "compatibility_score": None,
                "city": liker.location,
                "tag": _representative_tag(liker),
                "liked_at": liked_at,
            })

    return {
        "count": len(profiles),
        "is_premium": premium,
        "has_used_unlock_today": has_used_unlock_today,
        "profiles": profiles,
    }


@router.post("/unlock")
async def unlock_profile(
    body: UnlockRequest,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Reveal a single liker's full profile.

    Free users get FREE_UNLOCKS_PER_DAY unlocks per UTC-day; premium is
    unlimited. Idempotent: re-unlocking an already-unlocked profile returns it
    again without consuming quota.
    """
    now = _now()
    me = await _resolve_self(db, decoded_token["uid"])
    premium = _is_premium(me, now)

    target = (await db.execute(
        select(User).where(
            User.firebase_uid == body.firebase_uid_to_unlock,
            User.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Profile not found")
    if target.id == me.id:
        raise HTTPException(status_code=400, detail="Cannot unlock yourself")

    # Must actually be a liker you haven't responded to.
    if not await _liker_swipe(db, target.id, me.id):
        raise HTTPException(status_code=404, detail="This person hasn't liked you")
    if await _already_responded(db, me.id, target.id):
        raise HTTPException(status_code=409, detail="You've already responded to this like")

    existing = (await db.execute(
        select(PremiumUnlock).where(
            PremiumUnlock.user_id == me.id,
            PremiumUnlock.unlocked_user_id == target.id,
        )
    )).scalar_one_or_none()

    if existing is None:
        if not premium and await _unlocks_used_today(db, me.id, now) >= FREE_UNLOCKS_PER_DAY:
            raise HTTPException(
                status_code=403,
                detail="You've used your free unlock for today. Upgrade for unlimited unlocks.",
            )
        db.add(PremiumUnlock(user_id=me.id, unlocked_user_id=target.id, action=None))
        await db.commit()

    return {
        "profile": {
            "user_id": target.id,
            "firebase_uid": target.firebase_uid,
            "name": target.name,
            "age": target.age,
            "bio": target.bio,
            "profile_image_url": target.profile_image_url,
            "additional_image_urls": target.additional_image_urls,
            "interests": target.interests,
        }
    }


@router.post("/respond")
async def respond_to_like(
    body: RespondRequest,
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Like or pass an (unlocked) liker. A like is always a mutual match because
    the target already liked you. Records the swipe so the liker drops out of
    the received list, and stamps the unlock row's action/match_id.
    """
    action = body.action.lower().strip()
    if action not in ("like", "pass"):
        raise HTTPException(status_code=400, detail="action must be 'like' or 'pass'")

    now = _now()
    me = await _resolve_self(db, decoded_token["uid"])
    premium = _is_premium(me, now)

    target = (await db.execute(
        select(User).where(
            User.firebase_uid == body.liked_user_firebase_uid,
            User.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Profile not found")

    unlock = (await db.execute(
        select(PremiumUnlock).where(
            PremiumUnlock.user_id == me.id,
            PremiumUnlock.unlocked_user_id == target.id,
        )
    )).scalar_one_or_none()

    # Free users must unlock before responding; premium tiles are never blurred
    # so they may respond directly.
    if not premium and unlock is None:
        raise HTTPException(status_code=403, detail="Unlock this profile first")

    reciprocal = await _liker_swipe(db, target.id, me.id)

    # Record my swipe so the liker leaves the received pool (idempotent).
    if not await _already_responded(db, me.id, target.id):
        db.add(Swipe(swiper_id=me.id, swiped_id=target.id, liked=(action == "like")))

    match_id_int: int | None = None
    matched_user_name: str | None = None

    if action == "like" and reciprocal is not None:
        try:
            mid = await create_match_in_firestore(me.firebase_uid, target.firebase_uid, db)
            match_id_int = int(mid) if mid is not None else None
        except Exception:
            logger.warning("likes/respond: match creation failed", exc_info=True)
            match_id_int = None
        matched_user_name = _first_name(target.name) or "Someone"

    if unlock is not None:
        unlock.action = action
        if match_id_int is not None:
            unlock.match_id = match_id_int

    await db.commit()

    if match_id_int is not None:
        try:
            await push.notify_new_match(
                recipient=target,
                matcher_name=me.name or "Someone",
                match_id=match_id_int,
            )
        except Exception:
            logger.warning("likes/respond: new-match push failed", exc_info=True)

    return {
        "match_created": match_id_int is not None,
        "matched_user_name": matched_user_name,
        "match_id": match_id_int,
    }


@router.get("/unlock-status")
async def unlock_status(
    decoded_token=Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Premium/quota probe. No iOS caller yet; provided for completeness and
    forward use. `unlocks_remaining_today` is null for premium (unlimited)."""
    now = _now()
    me = await _resolve_self(db, decoded_token["uid"])
    premium = _is_premium(me, now)
    used = await _unlocks_used_today(db, me.id, now)
    return {
        "is_premium": premium,
        "has_used_unlock_today": used >= FREE_UNLOCKS_PER_DAY,
        "unlocks_remaining_today": None if premium else max(0, FREE_UNLOCKS_PER_DAY - used),
    }
