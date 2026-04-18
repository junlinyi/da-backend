"""
Feature Service — computes and caches per-user feature vectors.

The feature vector is a structured JSONB dict that the ranking algorithm
reads directly.  By precomputing and caching it here we keep ranking fast
and decouple data collection from scoring.

Schema of the features dict
───────────────────────────
{
  "values": {
    "relationship_goal_enc":  float,   # one-hot-like encoding 0-1
    "wants_children_enc":     float,
    "lifestyle":              [float, ...],  # 4 dims, 0-1 normalized
    "values_vec":             [float, ...],  # 6 dims, 0-1 normalized
    "personality":            [float, ...],  # Big Five, 0-1 normalized
    "communication":          float,
    "dealbreakers":           [bool, ...]    # 6 flags
  },
  "interests": {
    "categories": {str: float},  # 10 semantic buckets, 0-1 weight
    "raw":         [str]          # original interest list
  },
  "behavioral": {
    "like_rate":               float,   # likes / total swipes (null until ≥10)
    "message_rate":            float,   # matches with ≥1 message / total matches
    "call_rate":               float,   # matches with completed call / total matches
    "avg_call_rating_given":   float,   # mean rating given to others
    "avg_call_rating_received":float,
    "response_rate":           float,   # reciprocal messages / first messages sent
    "active_hour_mode":        int,     # 0-23 hour of peak activity
    "swipe_selectivity":       float    # same as like_rate (alias used externally)
  },
  "profile_completeness":     float,   # 0-1 signal of how much the user filled in
  "computed_at":              str      # ISO-8601 UTC timestamp
}
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import (
    User, UserValues, UserFeatureVector,
    Swipe, Match, MatchOutcome, BehavioralEvent, CallRating,
)

logger = logging.getLogger(__name__)

# ── Sentence-transformer model (lazy-loaded singleton) ────────────────────────
_embed_model = None

def _get_embed_model():
    """Load the sentence-transformer model once, on first use."""
    global _embed_model
    if _embed_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded sentence-transformer model: all-MiniLM-L6-v2")
        except Exception as exc:
            logger.warning(f"Could not load sentence-transformer: {exc}. Interest embedding disabled.")
            _embed_model = False   # sentinel: don't retry
    return _embed_model if _embed_model is not False else None

# ── Semantic interest categories ──────────────────────────────────────────────
INTEREST_CATEGORIES: Dict[str, list[str]] = {
    "outdoor_adventure": [
        "hiking", "camping", "rock climbing", "skiing", "surfing", "kayaking",
        "backpacking", "climbing", "trail running", "mountaineering", "sailing",
    ],
    "fitness_sports": [
        "gym", "yoga", "running", "cycling", "tennis", "basketball", "soccer",
        "swimming", "crossfit", "pilates", "football", "baseball", "golf",
        "martial arts", "boxing",
    ],
    "arts_culture": [
        "painting", "music", "theater", "museums", "photography", "writing",
        "poetry", "dance", "film", "art", "crafts", "sculpture", "cinema",
        "concerts", "opera",
    ],
    "tech_gaming": [
        "gaming", "technology", "coding", "ai", "sci-fi", "programming",
        "video games", "esports", "vr", "board games", "tabletop",
    ],
    "food_drink": [
        "cooking", "restaurants", "wine", "coffee", "baking", "foodie",
        "craft beer", "cocktails", "food", "culinary",
    ],
    "social_lifestyle": [
        "travel", "dancing", "parties", "festivals", "nightlife", "fashion",
        "shopping", "volunteering", "networking", "events",
    ],
    "intellectual": [
        "reading", "philosophy", "science", "economics", "history", "debate",
        "politics", "psychology", "literature", "podcasts", "news",
    ],
    "nature_animals": [
        "animals", "dogs", "cats", "nature", "gardening", "environment",
        "wildlife", "birdwatching", "astronomy",
    ],
    "family_home": [
        "family", "kids", "home improvement", "diy", "volunteering",
        "community", "parenting", "home decor",
    ],
    "wellness_spiritual": [
        "meditation", "spirituality", "wellness", "mindfulness", "yoga",
        "mental health", "self-improvement", "therapy",
    ],
}

RELATIONSHIP_GOAL_ORDER = ["casual", "open", "unsure", "long_term", "marriage"]
WANTS_CHILDREN_ORDER    = ["no", "has_and_done", "open", "has_and_wants_more", "yes"]


def _normalize(val: Optional[float], lo: float = 1.0, hi: float = 5.0) -> float:
    """Normalize a Likert 1-5 score to 0-1.  Returns 0.5 for None."""
    if val is None:
        return 0.5
    return (val - lo) / (hi - lo)


def _encode_categorical(value: Optional[str], ordered: list[str]) -> float:
    """Encode an ordered categorical to 0-1.  Returns 0.5 for unknown."""
    if value is None or value not in ordered:
        return 0.5
    return ordered.index(value) / max(len(ordered) - 1, 1)


def _compute_interest_embedding(interests: list[str]) -> Optional[list[float]]:
    """
    Compute a 384-dim sentence embedding from the user's raw interest list.
    Returns None if the model is unavailable or the list is empty.
    """
    if not interests:
        return None
    model = _get_embed_model()
    if model is None:
        return None
    text = ", ".join(interests)
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _compute_interest_categories(interests: list[str]) -> Dict[str, float]:
    """
    Map a user's free-text interests to semantic category weights.
    Weight = fraction of category keywords that appear in the user's interests
    (capped at 1.0).  Falls back to substring matching if exact match fails.
    """
    if not interests:
        return {k: 0.0 for k in INTEREST_CATEGORIES}

    lower_interests = [i.lower().strip() for i in interests]
    result: Dict[str, float] = {}

    for cat, keywords in INTEREST_CATEGORIES.items():
        hits = 0
        for kw in keywords:
            if any(kw in li or li in kw for li in lower_interests):
                hits += 1
        # Sigmoid-ish: at least 1 hit → meaningful score, caps at 1
        result[cat] = min(1.0, hits / max(3, len(keywords) * 0.4))

    return result


def _compute_values_features(uv: Optional[UserValues]) -> Dict[str, Any]:
    """Compute the values sub-vector from a UserValues row."""
    if uv is None:
        return {
            "relationship_goal_enc": 0.5,
            "wants_children_enc":    0.5,
            "lifestyle":             [0.5, 0.5, 0.5, 0.5],
            "values_vec":            [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            "personality":           [0.5, 0.5, 0.5, 0.5, 0.5],
            "communication":         0.5,
            "dealbreakers":          [False] * 6,
            "conflict_style":        "discuss",
        }

    return {
        "relationship_goal_enc": _encode_categorical(uv.relationship_goal, RELATIONSHIP_GOAL_ORDER),
        "wants_children_enc":    _encode_categorical(uv.wants_children,    WANTS_CHILDREN_ORDER),
        "lifestyle": [
            _normalize(uv.activity_level),
            _normalize(uv.social_energy),
            _normalize(uv.night_owl_score),
            _normalize(uv.travel_importance),
        ],
        "values_vec": [
            _normalize(uv.religious_importance),
            _normalize(uv.political_leaning),
            _normalize(uv.financial_priority),
            _normalize(uv.career_ambition),
            _normalize(uv.environmental_concern),
            0.5,  # placeholder for future dimension
        ],
        "personality": [
            _normalize(uv.big5_openness),
            _normalize(uv.big5_conscientiousness),
            _normalize(uv.big5_extraversion),
            _normalize(uv.big5_agreeableness),
            _normalize(uv.big5_neuroticism),
        ],
        "communication": _normalize(uv.communication_directness),
        "dealbreakers": [
            bool(uv.dealbreaker_smoking),
            bool(uv.dealbreaker_drugs),
            bool(uv.dealbreaker_drinking),
            bool(uv.dealbreaker_diff_religion),
            bool(uv.dealbreaker_diff_politics),
            bool(uv.dealbreaker_no_children),
        ],
        "conflict_style": uv.conflict_style or "discuss",
    }


def _decay_weight(ts: datetime, half_life_days: float = 30.0) -> float:
    """
    Exponential decay weight for a past event.
    Events from today get weight 1.0; events from `half_life_days` ago get 0.5.
    Uses UTC; ts may be naive (treated as UTC) or aware.
    """
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    days_ago = max(0.0, (now - ts).total_seconds() / 86400.0)
    return math.exp(-days_ago * math.log(2) / half_life_days)


async def _compute_behavioral_features(user_id: int, db: AsyncSession) -> Dict[str, Any]:
    """
    Compute behavioral features from swipe / match / call history.
    Recent events are weighted more heavily via exponential decay (half-life 30 days),
    so stale preference patterns don't dominate the feature vector.
    """

    # ── Swipe selectivity (like_rate) — decay-weighted ───────────────────────
    swipes_q = await db.execute(
        select(Swipe.liked, Swipe.timestamp).where(Swipe.swiper_id == user_id)
    )
    swipes = swipes_q.all()

    total_weight = sum(_decay_weight(s.timestamp) for s in swipes) if swipes else 0.0
    like_weight  = sum(_decay_weight(s.timestamp) for s in swipes if s.liked) if swipes else 0.0

    # Require at least the equivalent of 10 recent swipes worth of signal
    like_rate = (like_weight / total_weight) if total_weight >= 10.0 else None

    # ── Match → message rate ──────────────────────────────────────────────────
    outcomes_q = await db.execute(
        select(MatchOutcome).where(
            (MatchOutcome.user1_id == user_id) | (MatchOutcome.user2_id == user_id)
        )
    )
    outcomes = outcomes_q.scalars().all()
    total_matches = len(outcomes)
    messages_started = sum(1 for o in outcomes if o.first_message_at is not None)
    calls_completed  = sum(1 for o in outcomes if o.call_completed_at is not None)

    message_rate = (messages_started / total_matches) if total_matches >= 5 else None
    call_rate    = (calls_completed  / total_matches) if total_matches >= 5 else None

    # ── Response rate (reciprocal messages) ───────────────────────────────────
    reciprocal = sum(1 for o in outcomes if o.reciprocal_msg_at is not None)
    response_rate = (reciprocal / messages_started) if messages_started >= 3 else None

    # ── Call ratings ─────────────────────────────────────────────────────────
    ratings_given_q = await db.execute(
        select(func.avg(CallRating.rating)).where(CallRating.rater_id == user_id)
    )
    avg_given = ratings_given_q.scalar()

    ratings_recv_q = await db.execute(
        select(func.avg(CallRating.rating)).where(CallRating.rated_user_id == user_id)
    )
    avg_recv = ratings_recv_q.scalar()

    # ── Peak activity hour — weighted by recency ──────────────────────────────
    recent_swipes_q = await db.execute(
        select(Swipe.timestamp)
        .where(Swipe.swiper_id == user_id)
        .order_by(Swipe.timestamp.desc())
        .limit(50)
    )
    recent_ts = recent_swipes_q.scalars().all()
    if recent_ts:
        hour_weights: Dict[int, float] = {}
        for ts in recent_ts:
            h = ts.hour if ts else 0
            hour_weights[h] = hour_weights.get(h, 0.0) + _decay_weight(ts)
        active_hour_mode = max(hour_weights, key=hour_weights.get)
    else:
        active_hour_mode = 20  # default: 8 PM

    # ── Profile view engagement (time_on_card) ────────────────────────────────
    # Average seconds spent on cards before swiping — signals genuine interest vs snap-swipe
    view_events_q = await db.execute(
        select(BehavioralEvent.event_meta, BehavioralEvent.occurred_at)
        .where(
            BehavioralEvent.user_id == user_id,
            BehavioralEvent.event_type == "profile_view",
        )
        .order_by(BehavioralEvent.occurred_at.desc())
        .limit(100)
    )
    view_events = view_events_q.all()
    if view_events:
        durations = [
            e.event_meta.get("duration_seconds", 0)
            for e in view_events
            if e.event_meta and isinstance(e.event_meta.get("duration_seconds"), (int, float))
        ]
        avg_view_duration = sum(durations) / len(durations) if durations else None
    else:
        avg_view_duration = None

    return {
        "like_rate":                like_rate,
        "message_rate":             message_rate,
        "call_rate":                call_rate,
        "avg_call_rating_given":    float(avg_given) if avg_given else None,
        "avg_call_rating_received": float(avg_recv)  if avg_recv  else None,
        "response_rate":            response_rate,
        "active_hour_mode":         active_hour_mode,
        "swipe_selectivity":        like_rate,
        "avg_view_duration_s":      avg_view_duration,   # seconds on card before swiping
    }


def _compute_profile_completeness(user: User, uv: Optional[UserValues]) -> float:
    """Score 0-1 indicating how complete the user's profile is."""
    fields = [
        user.name, user.bio, user.age, user.gender,
        user.profile_image_url, user.interests,
        user.latitude, user.longitude,
    ]
    base = sum(1 for f in fields if f) / len(fields)
    values_bonus = 0.2 if uv is not None else 0.0
    prompts_bonus = 0.1 if user.prompts else 0.0
    return min(1.0, base * 0.7 + values_bonus + prompts_bonus)


async def compute_feature_vector(user_id: int, db: AsyncSession) -> Dict[str, Any]:
    """
    Compute the full feature vector for a user.
    Does NOT write to the DB — call upsert_feature_vector for that.
    """
    user_q = await db.execute(select(User).where(User.id == user_id))
    user   = user_q.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    uv_q = await db.execute(select(UserValues).where(UserValues.user_id == user_id))
    uv   = uv_q.scalar_one_or_none()

    interests_raw = user.interests or []

    values_features    = _compute_values_features(uv)
    interest_cats      = _compute_interest_categories(interests_raw)
    interest_embedding = _compute_interest_embedding(interests_raw)
    behavioral         = await _compute_behavioral_features(user_id, db)
    completeness       = _compute_profile_completeness(user, uv)

    interests_block: Dict[str, Any] = {
        "categories": interest_cats,
        "raw":         interests_raw,
    }
    if interest_embedding is not None:
        interests_block["embedding"] = interest_embedding

    return {
        "values":               values_features,
        "interests":            interests_block,
        "behavioral":           behavioral,
        "profile_completeness": completeness,
        "computed_at":          datetime.now(timezone.utc).isoformat(),
    }


async def upsert_feature_vector(user_id: int, db: AsyncSession) -> UserFeatureVector:
    """
    Compute and persist the feature vector for a user.
    Creates a new row if one doesn't exist, otherwise updates in place.
    """
    features = await compute_feature_vector(user_id, db)

    existing_q = await db.execute(
        select(UserFeatureVector).where(UserFeatureVector.user_id == user_id)
    )
    fv = existing_q.scalar_one_or_none()

    if fv:
        fv.features    = features
        fv.computed_at = datetime.now(timezone.utc)
        fv.version     += 1
    else:
        fv = UserFeatureVector(user_id=user_id, features=features)
        db.add(fv)

    await db.flush()
    return fv


async def get_feature_vector(user_id: int, db: AsyncSession) -> Optional[Dict[str, Any]]:
    """
    Return a cached feature vector, recomputing if stale (>24 h) or missing.
    """
    fv_q = await db.execute(
        select(UserFeatureVector).where(UserFeatureVector.user_id == user_id)
    )
    fv = fv_q.scalar_one_or_none()

    stale_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    if fv is None or fv.computed_at < stale_threshold:
        try:
            fv = await upsert_feature_vector(user_id, db)
            await db.commit()
        except Exception as exc:
            logger.warning(f"Feature vector recompute failed for user {user_id}: {exc}")
            return fv.features if fv else None

    return fv.features
