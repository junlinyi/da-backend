"""DB-bound tests for the premium-gated Likes tab (/likes/*).

Calls the router handlers directly with a fake decoded token + the Postgres
harness `db`, mirroring tests/test_match_state_db.py. Firestore match creation
and push are monkeypatched.
"""
import pytest
from sqlalchemy import select

from app import models
from app.routers import likes
from app.services import push_notification_service as push


@pytest.fixture(autouse=True)
def _patch_externals(monkeypatch):
    async def fake_create_match(uid1, uid2, db, **kw):
        # Stand in for the real Firestore+Postgres match creation: insert a real
        # Match row so the premium_unlocks.match_id FK is satisfiable, and return
        # its id as a string (the real helper returns the Postgres id stringified).
        u1 = (await db.execute(select(models.User).where(models.User.firebase_uid == uid1))).scalar_one()
        u2 = (await db.execute(select(models.User).where(models.User.firebase_uid == uid2))).scalar_one()
        m = models.Match(user_id=u1.id, matched_user_id=u2.id, status="accepted")
        db.add(m); await db.flush()
        return str(m.id)
    async def fake_push(**kw):
        return None
    monkeypatch.setattr(likes, "create_match_in_firestore", fake_create_match)
    monkeypatch.setattr(push, "notify_new_match", fake_push)


def _tok(user):
    return {"uid": user.firebase_uid}


async def _make_liker(db, make_user, *, me, **attrs):
    """A user with profile attrs who has right-swiped `me`."""
    u = await make_user(name=attrs.get("name", "Liker"))
    for k, v in attrs.items():
        setattr(u, k, v)
    db.add(models.Swipe(swiper_id=u.id, swiped_id=me.id, liked=True))
    await db.commit(); await db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# /likes/received
# ---------------------------------------------------------------------------

async def test_received_blurs_for_free_user(db, make_user):
    me = await make_user(name="Me")
    liker = await _make_liker(db, make_user, me=me,
                              name="Liker", profile_image_url="http://x/p.jpg",
                              location="Austin", interests=["climbing", "tea"])
    res = await likes.get_received_likes(decoded_token=_tok(me), db=db)
    assert res["is_premium"] is False
    assert res["count"] == 1
    p = res["profiles"][0]
    assert p["blurred"] is True
    assert p["first_name"] is None and p["photo_url"] is None
    assert p["city"] is None and p["tag"] is None
    assert p["user_id"] == liker.id and p["firebase_uid"] == liker.firebase_uid


async def test_received_unblurred_for_premium(db, make_user):
    me = await make_user(name="Me")
    me.is_premium = True
    await db.commit()
    await _make_liker(db, make_user, me=me, name="Liker Jones",
                      profile_image_url="http://x/p.jpg", location="Austin",
                      interests=["climbing", "tea"])
    res = await likes.get_received_likes(decoded_token=_tok(me), db=db)
    assert res["is_premium"] is True
    p = res["profiles"][0]
    assert p["blurred"] is False
    assert p["first_name"] == "Liker"        # first token only
    assert p["photo_url"] == "http://x/p.jpg"
    assert p["city"] == "Austin"
    assert p["tag"] == "climbing"            # first interest


async def test_received_excludes_already_responded(db, make_user):
    me = await make_user(name="Me")
    liker = await _make_liker(db, make_user, me=me, name="Liker")
    db.add(models.Swipe(swiper_id=me.id, swiped_id=liker.id, liked=False))
    await db.commit()
    res = await likes.get_received_likes(decoded_token=_tok(me), db=db)
    assert res["count"] == 0


async def test_received_unblurred_after_unlock(db, make_user):
    me = await make_user(name="Me")
    liker = await _make_liker(db, make_user, me=me, name="Liker",
                              location="Reno", interests=["surf"])
    await likes.unlock_profile(
        likes.UnlockRequest(firebase_uid_to_unlock=liker.firebase_uid),
        decoded_token=_tok(me), db=db)
    res = await likes.get_received_likes(decoded_token=_tok(me), db=db)
    p = res["profiles"][0]
    assert p["blurred"] is False
    assert p["city"] == "Reno" and p["tag"] == "surf"
    assert res["has_used_unlock_today"] is True


# ---------------------------------------------------------------------------
# /likes/unlock
# ---------------------------------------------------------------------------

async def test_unlock_free_daily_limit(db, make_user):
    me = await make_user(name="Me")
    a = await _make_liker(db, make_user, me=me, name="A")
    b = await _make_liker(db, make_user, me=me, name="B")
    await likes.unlock_profile(
        likes.UnlockRequest(firebase_uid_to_unlock=a.firebase_uid),
        decoded_token=_tok(me), db=db)
    with pytest.raises(Exception) as ei:
        await likes.unlock_profile(
            likes.UnlockRequest(firebase_uid_to_unlock=b.firebase_uid),
            decoded_token=_tok(me), db=db)
    assert getattr(ei.value, "status_code", None) == 403


async def test_unlock_premium_unlimited(db, make_user):
    me = await make_user(name="Me")
    me.is_premium = True
    await db.commit()
    a = await _make_liker(db, make_user, me=me, name="A")
    b = await _make_liker(db, make_user, me=me, name="B")
    await likes.unlock_profile(likes.UnlockRequest(firebase_uid_to_unlock=a.firebase_uid),
                               decoded_token=_tok(me), db=db)
    # Second unlock must NOT raise for premium.
    out = await likes.unlock_profile(likes.UnlockRequest(firebase_uid_to_unlock=b.firebase_uid),
                                     decoded_token=_tok(me), db=db)
    assert out["profile"]["user_id"] == b.id


async def test_unlock_idempotent_no_extra_quota(db, make_user):
    me = await make_user(name="Me")
    a = await _make_liker(db, make_user, me=me, name="A")
    await likes.unlock_profile(likes.UnlockRequest(firebase_uid_to_unlock=a.firebase_uid),
                               decoded_token=_tok(me), db=db)
    # Re-unlock same profile: allowed, still only one unlock used today.
    await likes.unlock_profile(likes.UnlockRequest(firebase_uid_to_unlock=a.firebase_uid),
                               decoded_token=_tok(me), db=db)
    status = await likes.unlock_status(decoded_token=_tok(me), db=db)
    assert status["unlocks_remaining_today"] == 0


async def test_unlock_non_liker_404(db, make_user):
    me = await make_user(name="Me")
    stranger = await make_user(name="Stranger")  # never liked me
    with pytest.raises(Exception) as ei:
        await likes.unlock_profile(
            likes.UnlockRequest(firebase_uid_to_unlock=stranger.firebase_uid),
            decoded_token=_tok(me), db=db)
    assert getattr(ei.value, "status_code", None) == 404


# ---------------------------------------------------------------------------
# /likes/respond
# ---------------------------------------------------------------------------

async def test_respond_like_creates_match(db, make_user):
    me = await make_user(name="Me")
    a = await _make_liker(db, make_user, me=me, name="Alex Doe")
    await likes.unlock_profile(likes.UnlockRequest(firebase_uid_to_unlock=a.firebase_uid),
                               decoded_token=_tok(me), db=db)
    out = await likes.respond_to_like(
        likes.RespondRequest(liked_user_firebase_uid=a.firebase_uid, action="like"),
        decoded_token=_tok(me), db=db)
    assert out["match_created"] is True
    assert out["matched_user_name"] == "Alex"
    assert isinstance(out["match_id"], int)
    # Liker drops out of the received pool.
    res = await likes.get_received_likes(decoded_token=_tok(me), db=db)
    assert res["count"] == 0
    # Unlock row stamped with action + match.
    unlock = (await db.execute(
        select(models.PremiumUnlock).where(models.PremiumUnlock.user_id == me.id)
    )).scalars().first()
    assert unlock.action == "like"
    assert unlock.match_id == out["match_id"]


async def test_respond_pass_drops_liker(db, make_user):
    me = await make_user(name="Me")
    a = await _make_liker(db, make_user, me=me, name="A")
    await likes.unlock_profile(likes.UnlockRequest(firebase_uid_to_unlock=a.firebase_uid),
                               decoded_token=_tok(me), db=db)
    out = await likes.respond_to_like(
        likes.RespondRequest(liked_user_firebase_uid=a.firebase_uid, action="pass"),
        decoded_token=_tok(me), db=db)
    assert out["match_created"] is False
    res = await likes.get_received_likes(decoded_token=_tok(me), db=db)
    assert res["count"] == 0


async def test_respond_free_requires_unlock(db, make_user):
    me = await make_user(name="Me")
    a = await _make_liker(db, make_user, me=me, name="A")
    with pytest.raises(Exception) as ei:
        await likes.respond_to_like(
            likes.RespondRequest(liked_user_firebase_uid=a.firebase_uid, action="like"),
            decoded_token=_tok(me), db=db)
    assert getattr(ei.value, "status_code", None) == 403


async def test_respond_premium_no_unlock_needed(db, make_user):
    me = await make_user(name="Me")
    me.is_premium = True
    await db.commit()
    a = await _make_liker(db, make_user, me=me, name="A")
    out = await likes.respond_to_like(
        likes.RespondRequest(liked_user_firebase_uid=a.firebase_uid, action="like"),
        decoded_token=_tok(me), db=db)
    assert out["match_created"] is True
