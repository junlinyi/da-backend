import pytest
from sqlalchemy.exc import IntegrityError
from app import models

@pytest.mark.asyncio
async def test_harness_boots(make_user, make_match, client_as):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b)
    assert m.id is not None
    async with client_as(a) as c:
        r = await c.get("/scheduling/me/upcoming-calls")
        assert r.status_code in (200, 404)  # endpoint may not exist yet


@pytest.mark.asyncio
async def test_check_constraints_live(make_user, make_match, db):
    a = await make_user(name="Ca"); b = await make_user(name="Cb")
    m = await make_match(a, b)
    m.text_state = "bogus"          # violates chk_text_state
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_one_pending_proposal_per_match(make_user, make_match, db):
    from datetime import datetime, timedelta, timezone
    a = await make_user(name="Pa"); b = await make_user(name="Pb")
    m = await make_match(a, b)
    now = datetime.now(timezone.utc)
    db.add(models.VideoCallProposal(match_id=m.id, proposer_user_id=a.id,
        proposed_start_utc=now+timedelta(hours=2), proposed_end_utc=now+timedelta(hours=2, minutes=30), status="pending"))
    await db.commit()
    db.add(models.VideoCallProposal(match_id=m.id, proposer_user_id=b.id,
        proposed_start_utc=now+timedelta(hours=3), proposed_end_utc=now+timedelta(hours=3, minutes=30), status="pending"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
