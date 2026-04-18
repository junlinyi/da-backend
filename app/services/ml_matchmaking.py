"""
ML Matchmaking Service — Enhanced multi-factor compatibility scoring.

Architecture
────────────
Stage 1 — Hard Filters
    Gender preference, age range, distance limit, block/report list,
    already-swiped, already-matched.

Stage 2 — Multi-Factor Scoring
    Score = weighted sum of five component scores (all 0–1):

    ┌─────────────────────────────────┬────────┐
    │ Component                       │ Weight │
    ├─────────────────────────────────┼────────┤
    │ Values alignment                │  0.35  │
    │ Personality compatibility       │  0.20  │
    │ Interest semantic similarity    │  0.15  │
    │ Collaborative signal            │  0.15  │  ← 0 until ≥50 swipes exist
    │ Activity & lifestyle proximity  │  0.10  │
    │ Engagement quality boost        │  0.05  │
    └─────────────────────────────────┴────────┘

Stage 3 — Diversity Injection
    Insert ≥1 serendipity candidate (score 0.35-0.55) into every batch of 7
    to prevent filter-bubble collapse.

Stage 4 — Sorting + Dedup
    Sort by final score descending.  Return top N.

Deal-breaker Logic
──────────────────
If a candidate's stored values would trigger one of the current user's
deal-breakers (or vice versa), the candidate is excluded regardless of score.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Dict, Any, List, Tuple, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from geopy.distance import geodesic

from app.models import User, Swipe, Conversation, Report, UserValues
from app.services.feature_service import get_feature_vector

logger = logging.getLogger(__name__)

# ── Scoring weights ───────────────────────────────────────────────────────────
W_VALUES      = 0.35
W_PERSONALITY = 0.20
W_INTERESTS   = 0.15
W_COLLAB      = 0.15
W_ACTIVITY    = 0.10
W_ENGAGEMENT  = 0.05

MIN_SCORE       = 0.30   # candidates below this are excluded
DIVERSITY_FRAC  = 0.15   # fraction of batch that may be serendipity picks
COLLAB_MIN_DATA = 50     # minimum total swipes before collaborative signal is used


# ── Similarity helpers ────────────────────────────────────────────────────────

def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two equal-length lists."""
    if not a or not b or len(a) != len(b):
        return 0.5
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.5
    return (dot / (na * nb) + 1) / 2   # re-scale [-1,1] → [0,1]


def _l1_distance_score(a: List[float], b: List[float]) -> float:
    """Score = 1 - mean absolute difference.  Both lists 0-1 normalised."""
    if not a or not b or len(a) != len(b):
        return 0.5
    return 1.0 - sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _scalar_proximity(a: Optional[float], b: Optional[float]) -> float:
    """Scalar distance score for single normalised 0-1 values."""
    if a is None or b is None:
        return 0.5
    return 1.0 - abs(a - b)


# ── Component scoring ─────────────────────────────────────────────────────────

def score_values(fv1: Dict[str, Any], fv2: Dict[str, Any]) -> float:
    """
    Values alignment score (0-1).

    - Relationship goal & child plans: must be directionally compatible;
      score drops sharply for mismatches.
    - Lifestyle & values vectors: L1 proximity.
    - Communication style: scalar proximity.
    """
    v1 = fv1.get("values", {})
    v2 = fv2.get("values", {})

    if not v1 or not v2:
        return 0.5

    # Relationship goal alignment (high weight — core compatibility signal)
    rg_diff  = abs(v1.get("relationship_goal_enc", 0.5) - v2.get("relationship_goal_enc", 0.5))
    rg_score = max(0.0, 1.0 - rg_diff * 2.5)   # penalise heavily past 0.4 diff

    # Children plans alignment
    wc_diff  = abs(v1.get("wants_children_enc", 0.5) - v2.get("wants_children_enc", 0.5))
    wc_score = max(0.0, 1.0 - wc_diff * 2.0)

    # Lifestyle (activity, social, night-owl, travel)
    ls_score = _l1_distance_score(
        v1.get("lifestyle", [0.5]*4), v2.get("lifestyle", [0.5]*4)
    )

    # Core values (religious, political, financial, career, environment)
    val_score = _l1_distance_score(
        v1.get("values_vec", [0.5]*6), v2.get("values_vec", [0.5]*6)
    )

    # Communication style
    comm_score = _scalar_proximity(
        v1.get("communication"), v2.get("communication")
    )

    return (
        rg_score  * 0.30 +
        wc_score  * 0.20 +
        ls_score  * 0.20 +
        val_score * 0.20 +
        comm_score * 0.10
    )


def score_personality(fv1: Dict[str, Any], fv2: Dict[str, Any]) -> float:
    """
    Big Five compatibility score (0-1).

    Research findings encoded:
    - Agreeableness, Conscientiousness, Openness: similarity preferred
    - Extraversion: mild complementarity tolerated (opposite slightly ok)
    - Neuroticism: both low is best; both high is worst
    """
    p1 = fv1.get("values", {}).get("personality", [0.5]*5)
    p2 = fv2.get("values", {}).get("personality", [0.5]*5)

    if len(p1) < 5 or len(p2) < 5:
        return 0.5

    o1, c1, e1, a1, n1 = p1
    o2, c2, e2, a2, n2 = p2

    # Similarity-preferred dimensions (higher = more similar = better)
    o_score = 1.0 - abs(o1 - o2)
    c_score = 1.0 - abs(c1 - c2)
    a_score = 1.0 - abs(a1 - a2)

    # Extraversion: some evidence for similarity, slight complementarity ok
    e_score = 1.0 - abs(e1 - e2) * 0.7   # softer penalty

    # Neuroticism: penalise both being high (sum > 0.8 of max is bad)
    n_sum   = n1 + n2   # 0-2 range (both 0-1)
    n_score = max(0.0, 1.0 - n_sum * 0.6)

    return o_score * 0.25 + c_score * 0.25 + a_score * 0.20 + e_score * 0.15 + n_score * 0.15


def score_interests(fv1: Dict[str, Any], fv2: Dict[str, Any]) -> float:
    """
    Semantic interest similarity (0-1).

    Priority order:
    1. Sentence-transformer embeddings (384-dim cosine) — most accurate, uses
       semantic meaning so "trail running" and "hiking" score similarly.
    2. 10-bucket category cosine — fast fallback if embeddings unavailable.
    3. Raw Jaccard overlap — last resort for sparse profiles.
    """
    int1 = fv1.get("interests", {})
    int2 = fv2.get("interests", {})

    # ── 1. Embedding-based similarity (preferred) ─────────────────────────────
    emb1 = int1.get("embedding")
    emb2 = int2.get("embedding")
    if emb1 and emb2 and len(emb1) == len(emb2):
        # Embeddings are L2-normalised at compute time, so dot = cosine similarity
        dot = sum(a * b for a, b in zip(emb1, emb2))
        # dot ∈ [-1, 1]; remap to [0, 1] and blend with 0.5 floor to avoid
        # over-penalising totally unrelated but benign interests
        raw_sim = (dot + 1.0) / 2.0
        return max(0.0, min(1.0, raw_sim * 0.9 + 0.05))   # soften extremes

    # ── 2. Category bucket cosine ─────────────────────────────────────────────
    cats1 = int1.get("categories", {})
    cats2 = int2.get("categories", {})

    if cats1 and cats2:
        keys = sorted(cats1.keys())
        vec1 = [cats1.get(k, 0.0) for k in keys]
        vec2 = [cats2.get(k, 0.0) for k in keys]
        return _cosine(vec1, vec2)

    # ── 3. Jaccard fallback ───────────────────────────────────────────────────
    raw1 = {i.lower() for i in int1.get("raw", [])}
    raw2 = {i.lower() for i in int2.get("raw", [])}
    if not raw1 or not raw2:
        return 0.3
    return len(raw1 & raw2) / len(raw1 | raw2)


def score_collaborative(
    user_id: int,
    candidate_id: int,
    total_swipes: int,
) -> float:
    """
    Placeholder collaborative filtering score.

    Currently returns 0.5 (neutral) until we have sufficient data (≥ COLLAB_MIN_DATA
    swipes).  Will be replaced with a real model (e.g. matrix factorisation or
    BPR) once data accumulates.

    The signal we'll ultimately use:
      "Users with similar swipe patterns also liked this candidate."
    """
    if total_swipes < COLLAB_MIN_DATA:
        return 0.5   # neutral — no data yet

    # TODO: query precomputed user-similarity embeddings from DB
    # and compute dot-product score against candidate.
    return 0.5


def score_activity(
    user: User,
    candidate: User,
    fv1: Dict[str, Any],
    fv2: Dict[str, Any],
) -> float:
    """
    Activity & lifestyle proximity score (0-1).

    Factors:
    - Distance (lower weight than original algo; app is video-first)
    - Active-hour alignment (night owl vs. morning person)
    - Profile recency (recently active users scored higher)
    """
    score = 0.0

    # Distance (40% of this sub-score) — use the more restrictive preference of both users
    if all([user.latitude, user.longitude, candidate.latitude, candidate.longitude]):
        dist_km  = geodesic(
            (user.latitude, user.longitude),
            (candidate.latitude, candidate.longitude)
        ).kilometers
        # Respect both users' distance limits: a match only works if both are ok with it
        max_dist = min(
            user.max_distance_km or 32,
            candidate.max_distance_km or 32,
        )
        dist_score = max(0.0, 1.0 - (dist_km / max(max_dist, 1)))
    else:
        dist_score = 0.5
    score += dist_score * 0.40

    # Active-hour alignment (within 2h = high; >5h = low)
    h1 = fv1.get("behavioral", {}).get("active_hour_mode", 20)
    h2 = fv2.get("behavioral", {}).get("active_hour_mode", 20)
    hour_diff    = min(abs(h1 - h2), 24 - abs(h1 - h2))  # circular
    hour_score   = max(0.0, 1.0 - hour_diff / 12.0)
    score       += hour_score * 0.30

    # Recency (was the candidate active in the last 7 days?)
    from datetime import datetime, timezone, timedelta
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    if candidate.last_active and candidate.last_active > week_ago:
        score += 0.30
    elif candidate.last_active:
        days_inactive = (datetime.now(timezone.utc) - candidate.last_active).days
        score += max(0.0, 0.30 - (days_inactive / 30) * 0.30)

    return min(1.0, score)


def score_engagement_quality(fv1: Dict[str, Any], fv2: Dict[str, Any]) -> float:
    """
    Engagement quality boost (0-1).

    Rewards users who tend to have deep conversations and good call outcomes.
    Both participants' profiles contribute.
    """
    b1 = fv1.get("behavioral", {})
    b2 = fv2.get("behavioral", {})

    scores = []
    for b in (b1, b2):
        s = 0.5   # neutral default
        if b.get("message_rate") is not None:
            s += (b["message_rate"] - 0.5) * 0.3
        if b.get("call_rate") is not None:
            s += (b["call_rate"] - 0.3) * 0.2
        if b.get("avg_call_rating_received") is not None:
            s += ((b["avg_call_rating_received"] - 3.0) / 2.0) * 0.2
        scores.append(min(1.0, max(0.0, s)))

    return sum(scores) / len(scores) if scores else 0.5


def _check_dealbreakers(
    uv_user: Optional[UserValues],
    uv_candidate: Optional[UserValues],
    candidate_user: User,
) -> bool:
    """
    Return True if a dealbreaker is triggered (candidate should be excluded).
    Checks both directions.
    """
    if uv_user is None or uv_candidate is None:
        return False   # no data → assume compatible

    # User's dealbreakers applied to candidate's profile
    # (We approximate: if user dealbreakers_diff_religion=True and
    #  |religious_importance difference| > 2 Likert steps, exclude.)
    def _religion_clash(uv_a: UserValues, uv_b: UserValues) -> bool:
        if not uv_a.dealbreaker_diff_religion:
            return False
        ri_a = uv_a.religious_importance or 3
        ri_b = uv_b.religious_importance or 3
        # If one is very religious (≥4) and the other not (≤2), that's a clash
        return (ri_a >= 4 and ri_b <= 2) or (ri_b >= 4 and ri_a <= 2)

    def _politics_clash(uv_a: UserValues, uv_b: UserValues) -> bool:
        if not uv_a.dealbreaker_diff_politics:
            return False
        pl_a = uv_a.political_leaning or 3
        pl_b = uv_b.political_leaning or 3
        return abs(pl_a - pl_b) >= 3   # at least 3 Likert steps apart

    def _children_clash(uv_a: UserValues, uv_b: UserValues) -> bool:
        if not uv_a.dealbreaker_no_children:
            return False
        return uv_b.wants_children in ("no", "has_and_done")

    clashes = [
        _religion_clash(uv_user, uv_candidate),
        _religion_clash(uv_candidate, uv_user),
        _politics_clash(uv_user, uv_candidate),
        _politics_clash(uv_candidate, uv_user),
        _children_clash(uv_user, uv_candidate),
        _children_clash(uv_candidate, uv_user),
    ]
    return any(clashes)


def _score_one_direction(
    viewer: User,
    subject: User,
    fv_viewer: Dict[str, Any],
    fv_subject: Dict[str, Any],
    total_swipes: int,
) -> float:
    """
    Score subject from viewer's perspective.

    Most components are symmetric (shared values, shared personality), but
    the selectivity adjustment makes this directional: a very picky user
    (low like_rate) applies a heavier penalty to borderline matches, while
    a more open user is more forgiving.  This approximates P(viewer → subject).
    """
    s_values      = score_values(fv_viewer, fv_subject)
    s_personality = score_personality(fv_viewer, fv_subject)
    s_interests   = score_interests(fv_viewer, fv_subject)
    s_collab      = score_collaborative(viewer.id, subject.id, total_swipes)
    s_activity    = score_activity(viewer, subject, fv_viewer, fv_subject)
    s_engagement  = score_engagement_quality(fv_viewer, fv_subject)

    raw = (
        s_values      * W_VALUES +
        s_personality * W_PERSONALITY +
        s_interests   * W_INTERESTS +
        s_collab      * W_COLLAB +
        s_activity    * W_ACTIVITY +
        s_engagement  * W_ENGAGEMENT
    )

    # Selectivity adjustment: picky users score candidates more conservatively.
    # like_rate of 0.1 → 10% compression; 0.5 → neutral; 1.0 → slight boost.
    like_rate = fv_viewer.get("behavioral", {}).get("like_rate")
    if like_rate is not None:
        # Map [0, 1] like_rate to a multiplier [0.88, 1.06]
        selectivity_mult = 0.88 + like_rate * 0.18
        raw = raw * selectivity_mult

    return min(1.0, max(0.0, raw))


def compute_compatibility_score(
    user: User,
    candidate: User,
    fv_user: Dict[str, Any],
    fv_candidate: Dict[str, Any],
    total_swipes: int,
) -> float:
    """
    Final bidirectional compatibility score (0-1) for a user ↔ candidate pair.

    Computes P(user → candidate) and P(candidate → user) separately, then
    takes the geometric mean — the score is high only if both directions look
    promising.  This prevents one very open user from inflating scores with
    everyone.
    """
    s_forward = _score_one_direction(user, candidate, fv_user, fv_candidate, total_swipes)
    s_reverse = _score_one_direction(candidate, user, fv_candidate, fv_user, total_swipes)

    # Geometric mean: punishes large asymmetries more than arithmetic mean would
    bidirectional = math.sqrt(s_forward * s_reverse)

    # Profile completeness penalty: users with sparse profiles score lower
    pc1 = fv_user.get("profile_completeness", 0.5)
    pc2 = fv_candidate.get("profile_completeness", 0.5)
    completeness_factor = (pc1 + pc2) / 2.0

    # Apply completeness scaling (0.6-1.0 range so very sparse profiles lose ≤40%)
    return round(bidirectional * (0.6 + completeness_factor * 0.4), 4)


# ── Main matching function ────────────────────────────────────────────────────

async def find_matches_ml(
    user_id: int,
    db: AsyncSession,
    limit: int = 7,
    min_score: float = MIN_SCORE,
) -> List[Tuple[User, float]]:
    """
    Return up to `limit` ranked candidates for `user_id`.

    Steps:
    1. Load current user + their feature vector
    2. Determine exclusion sets (swiped, matched, blocked, reported)
    3. Apply hard filters (gender, age, distance)
    4. Score each candidate with compute_compatibility_score
    5. Inject diversity candidates
    6. Sort and return top N
    """
    # ── 1. Load current user ─────────────────────────────────────────────────
    user_q = await db.execute(select(User).where(User.id == user_id))
    user   = user_q.scalar_one_or_none()
    if not user:
        return []

    fv_user = await get_feature_vector(user_id, db) or {}

    # Load user's UserValues for dealbreaker checks
    uv_user_q = await db.execute(select(UserValues).where(UserValues.user_id == user_id))
    uv_user   = uv_user_q.scalar_one_or_none()

    # ── 2. Exclusion sets ────────────────────────────────────────────────────
    swiped_q = await db.execute(
        select(Swipe.swiped_id).where(Swipe.swiper_id == user_id)
    )
    swiped_ids = {r for r in swiped_q.scalars()}

    conv_q = await db.execute(
        select(Conversation).where(
            or_(Conversation.user1_id == user_id, Conversation.user2_id == user_id)
        )
    )
    matched_ids = {
        c.user2_id if c.user1_id == user_id else c.user1_id
        for c in conv_q.scalars()
    }

    blocked_q = await db.execute(
        select(Report.reported_user_id).where(
            and_(Report.reporter_id == user_id, Report.status != "dismissed")
        )
    )
    blocked_ids = {r for r in blocked_q.scalars()}

    # Users who blocked me
    blocker_q = await db.execute(
        select(Report.reporter_id).where(
            and_(Report.reported_user_id == user_id, Report.status != "dismissed")
        )
    )
    blocker_ids = {r for r in blocker_q.scalars()}

    exclude_ids = swiped_ids | matched_ids | blocked_ids | blocker_ids | {user_id}

    # ── 3. Hard-filter candidate pool ────────────────────────────────────────
    gender_filter = [user.preferred_gender] if user.preferred_gender and user.preferred_gender != "any" else None
    min_age = user.min_age_preference or 18
    max_age = user.max_age_preference or 120

    candidate_q = select(User).where(
        User.id.not_in(exclude_ids),
        User.profile_completed == True,   # DB-03: only show complete profiles
        User.is_active == True,
        User.name.is_not(None),
        User.age.is_not(None),
        User.gender.is_not(None),
        User.age.between(min_age, max_age),
    )
    if gender_filter:
        candidate_q = candidate_q.where(
            or_(User.gender.in_(gender_filter), User.gender == "any")
        )

    candidates_result = await db.execute(candidate_q)
    candidates = candidates_result.scalars().all()

    # Distance filter
    max_dist = user.max_distance_km or 32
    if user.latitude and user.longitude:
        candidates = [
            c for c in candidates
            if not (c.latitude and c.longitude) or
               geodesic((user.latitude, user.longitude), (c.latitude, c.longitude)).kilometers <= max_dist * 1.2
            # 20% buffer: final sort may include slightly-outside candidates for serendipity
        ]

    # ── Count swipes for collaborative signal ────────────────────────────────
    total_swipes_q = await db.execute(
        select(Swipe).where(Swipe.swiper_id == user_id)
    )
    total_swipes = len(total_swipes_q.scalars().all())

    # ── 4. Score each candidate ──────────────────────────────────────────────
    scored: List[Tuple[User, float]] = []
    serendipity: List[Tuple[User, float]] = []   # candidates 0.35-0.55 for diversity

    # Pre-load UserValues for all candidates (batch)
    candidate_ids = [c.id for c in candidates]
    uv_q = await db.execute(
        select(UserValues).where(UserValues.user_id.in_(candidate_ids))
    )
    uv_map: Dict[int, UserValues] = {uv.user_id: uv for uv in uv_q.scalars()}

    for candidate in candidates:
        # Feature vector (may be stale or missing — that's ok for ranking)
        fv_cand = await get_feature_vector(candidate.id, db) or {}

        uv_candidate = uv_map.get(candidate.id)

        # Deal-breaker exclusion
        if _check_dealbreakers(uv_user, uv_candidate, candidate):
            continue

        final_score = compute_compatibility_score(
            user, candidate, fv_user, fv_cand, total_swipes
        )

        if final_score >= min_score:
            scored.append((candidate, final_score))
        elif MIN_SCORE * 0.85 <= final_score < min_score:
            serendipity.append((candidate, final_score))

    # ── 5. Diversity injection ───────────────────────────────────────────────
    scored.sort(key=lambda x: x[1], reverse=True)

    if serendipity and len(scored) < limit:
        # Fill remaining slots with serendipity picks
        random.shuffle(serendipity)
        scored.extend(serendipity[: limit - len(scored)])
    elif serendipity and len(scored) >= limit:
        # Replace the last diversity_frac of the batch with serendipity
        n_diversity = max(1, int(limit * DIVERSITY_FRAC))
        random.shuffle(serendipity)
        scored = scored[:limit - n_diversity] + serendipity[:n_diversity]

    # Final sort and trim
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]
