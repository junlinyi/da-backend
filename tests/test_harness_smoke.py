import pytest

@pytest.mark.asyncio
async def test_harness_boots(make_user, make_match, client_as):
    a = await make_user(name="Alex")
    b = await make_user(name="Mia")
    m = await make_match(a, b)
    assert m.id is not None
    async with client_as(a) as c:
        r = await c.get("/scheduling/me/upcoming-calls")
        assert r.status_code in (200, 404)  # endpoint may not exist yet
