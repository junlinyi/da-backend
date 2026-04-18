"""
Values Questionnaire Router
────────────────────────────
GET  /questionnaire/me          — fetch current user's answers (or null)
POST /questionnaire/me          — submit / update answers (triggers feature recompute)
GET  /questionnaire/questions   — return the question list with metadata (for iOS rendering)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import verify_firebase_token
from app.models import User, UserValues
from app.services.feature_service import upsert_feature_vector

import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ValuesSubmission(BaseModel):
    # Relationship intent
    relationship_goal: str = Field("long_term", pattern=r"^(long_term|marriage|casual|open|unsure)$")

    # Family
    wants_children: str = Field("open", pattern=r"^(yes|no|open|has_and_wants_more|has_and_done)$")
    children_timeline_years: Optional[int] = Field(None, ge=0, le=20)

    # Lifestyle (1-5 Likert)
    activity_level:    Optional[int] = Field(None, ge=1, le=5)
    social_energy:     Optional[int] = Field(None, ge=1, le=5)
    night_owl_score:   Optional[int] = Field(None, ge=1, le=5)
    travel_importance: Optional[int] = Field(None, ge=1, le=5)

    # Values
    religious_importance:  Optional[int] = Field(None, ge=1, le=5)
    religion:              Optional[str] = Field(None, max_length=50)
    political_leaning:     Optional[int] = Field(None, ge=1, le=5)
    financial_priority:    Optional[int] = Field(None, ge=1, le=5)
    career_ambition:       Optional[int] = Field(None, ge=1, le=5)
    environmental_concern: Optional[int] = Field(None, ge=1, le=5)

    # Big Five (1.0-5.0)
    big5_openness:          Optional[float] = Field(None, ge=1, le=5)
    big5_conscientiousness: Optional[float] = Field(None, ge=1, le=5)
    big5_extraversion:      Optional[float] = Field(None, ge=1, le=5)
    big5_agreeableness:     Optional[float] = Field(None, ge=1, le=5)
    big5_neuroticism:       Optional[float] = Field(None, ge=1, le=5)

    # Communication
    communication_directness: Optional[int] = Field(None, ge=1, le=5)
    conflict_style: Optional[str] = Field(None, pattern=r"^(discuss|cool_off|avoid|mixed)$")

    # Deal-breakers
    dealbreaker_smoking:       bool = False
    dealbreaker_drugs:         bool = False
    dealbreaker_drinking:      bool = False
    dealbreaker_diff_religion: bool = False
    dealbreaker_diff_politics: bool = False
    dealbreaker_no_children:   bool = False


class ValuesResponse(ValuesSubmission):
    completed_at: Optional[datetime] = None
    updated_at:   Optional[datetime] = None


class QuestionMeta(BaseModel):
    id:       str
    section:  str
    text:     str
    type:     str          # likert5 | multiple_choice | boolean | text
    options:  Optional[List[dict]] = None
    field:    str          # maps to ValuesSubmission field name


# ── Question definitions (sent to iOS for rendering) ─────────────────────────

QUESTIONS: List[dict] = [
    # ── Relationship Intent ──────────────────────────────────────────────────
    {
        "id": "q_rel_goal", "section": "Relationship",
        "text": "What are you looking for?",
        "type": "multiple_choice", "field": "relationship_goal",
        "options": [
            {"value": "marriage",   "label": "Marriage"},
            {"value": "long_term",  "label": "Long-term relationship"},
            {"value": "open",       "label": "Open to anything"},
            {"value": "casual",     "label": "Something casual"},
            {"value": "unsure",     "label": "Still figuring it out"},
        ]
    },

    # ── Family ───────────────────────────────────────────────────────────────
    {
        "id": "q_children", "section": "Family",
        "text": "Do you want children?",
        "type": "multiple_choice", "field": "wants_children",
        "options": [
            {"value": "yes",               "label": "Yes, I want children"},
            {"value": "has_and_wants_more", "label": "I have kids and want more"},
            {"value": "open",              "label": "Open to it"},
            {"value": "has_and_done",      "label": "I have kids and I'm done"},
            {"value": "no",               "label": "No, I don't want children"},
        ]
    },
    {
        "id": "q_children_timeline", "section": "Family",
        "text": "If yes, roughly when are you thinking? (years from now)",
        "type": "number", "field": "children_timeline_years",
        "options": None
    },

    # ── Lifestyle ────────────────────────────────────────────────────────────
    {
        "id": "q_activity", "section": "Lifestyle",
        "text": "How physically active is your lifestyle?",
        "type": "likert5", "field": "activity_level",
        "options": [
            {"value": 1, "label": "Rarely exercise"},
            {"value": 3, "label": "Moderately active"},
            {"value": 5, "label": "Very active / fitness-focused"},
        ]
    },
    {
        "id": "q_social", "section": "Lifestyle",
        "text": "How do you recharge?",
        "type": "likert5", "field": "social_energy",
        "options": [
            {"value": 1, "label": "Alone time (introvert)"},
            {"value": 3, "label": "Mix of both"},
            {"value": 5, "label": "Around people (extrovert)"},
        ]
    },
    {
        "id": "q_night_owl", "section": "Lifestyle",
        "text": "Are you more of a morning person or night owl?",
        "type": "likert5", "field": "night_owl_score",
        "options": [
            {"value": 1, "label": "Early bird"},
            {"value": 3, "label": "Somewhere in between"},
            {"value": 5, "label": "Night owl"},
        ]
    },
    {
        "id": "q_travel", "section": "Lifestyle",
        "text": "How important is travel to you?",
        "type": "likert5", "field": "travel_importance",
        "options": [
            {"value": 1, "label": "Not important"},
            {"value": 3, "label": "Nice to have"},
            {"value": 5, "label": "Essential part of my life"},
        ]
    },

    # ── Values ───────────────────────────────────────────────────────────────
    {
        "id": "q_religion_imp", "section": "Values",
        "text": "How important is religion / spirituality in your life?",
        "type": "likert5", "field": "religious_importance",
        "options": [
            {"value": 1, "label": "Not at all important"},
            {"value": 3, "label": "Somewhat important"},
            {"value": 5, "label": "Central to my life"},
        ]
    },
    {
        "id": "q_politics", "section": "Values",
        "text": "Politically, where do you fall?",
        "type": "likert5", "field": "political_leaning",
        "options": [
            {"value": 1, "label": "Very progressive"},
            {"value": 3, "label": "Moderate"},
            {"value": 5, "label": "Very conservative"},
        ]
    },
    {
        "id": "q_financial", "section": "Values",
        "text": "What's your financial style?",
        "type": "likert5", "field": "financial_priority",
        "options": [
            {"value": 1, "label": "Spend and enjoy now"},
            {"value": 3, "label": "Balance spending and saving"},
            {"value": 5, "label": "Frugal / save-focused"},
        ]
    },
    {
        "id": "q_career", "section": "Values",
        "text": "How career-focused are you?",
        "type": "likert5", "field": "career_ambition",
        "options": [
            {"value": 1, "label": "Work to live"},
            {"value": 3, "label": "Balanced"},
            {"value": 5, "label": "Highly career-driven"},
        ]
    },
    {
        "id": "q_environment", "section": "Values",
        "text": "How important is environmental sustainability to you?",
        "type": "likert5", "field": "environmental_concern",
        "options": [
            {"value": 1, "label": "Not a priority"},
            {"value": 3, "label": "I try when convenient"},
            {"value": 5, "label": "Core to my values"},
        ]
    },

    # ── Big Five ─────────────────────────────────────────────────────────────
    {
        "id": "q_openness", "section": "Personality",
        "text": "How much do you enjoy new experiences and abstract ideas?",
        "type": "likert5", "field": "big5_openness",
        "options": [
            {"value": 1, "label": "I prefer routine and the familiar"},
            {"value": 3, "label": "Somewhere in the middle"},
            {"value": 5, "label": "I love novelty and big ideas"},
        ]
    },
    {
        "id": "q_conscientiousness", "section": "Personality",
        "text": "How organised and detail-oriented are you?",
        "type": "likert5", "field": "big5_conscientiousness",
        "options": [
            {"value": 1, "label": "Spontaneous and flexible"},
            {"value": 3, "label": "Moderately organised"},
            {"value": 5, "label": "Very structured and planned"},
        ]
    },
    {
        "id": "q_agreeableness", "section": "Personality",
        "text": "How would you describe your social style?",
        "type": "likert5", "field": "big5_agreeableness",
        "options": [
            {"value": 1, "label": "Direct, competitive, say it like it is"},
            {"value": 3, "label": "Mix of assertive and accommodating"},
            {"value": 5, "label": "Warm, collaborative, put others first"},
        ]
    },
    {
        "id": "q_neuroticism", "section": "Personality",
        "text": "How do you handle stress and emotional ups-and-downs?",
        "type": "likert5", "field": "big5_neuroticism",
        "options": [
            {"value": 1, "label": "Very calm and stable"},
            {"value": 3, "label": "Occasionally stressed"},
            {"value": 5, "label": "I feel things very intensely"},
        ]
    },

    # ── Communication ────────────────────────────────────────────────────────
    {
        "id": "q_directness", "section": "Communication",
        "text": "How do you communicate in relationships?",
        "type": "likert5", "field": "communication_directness",
        "options": [
            {"value": 1, "label": "Subtle and indirect"},
            {"value": 3, "label": "Context-dependent"},
            {"value": 5, "label": "Very direct and explicit"},
        ]
    },
    {
        "id": "q_conflict", "section": "Communication",
        "text": "When you disagree with a partner, you prefer to:",
        "type": "multiple_choice", "field": "conflict_style",
        "options": [
            {"value": "discuss",  "label": "Talk it through immediately"},
            {"value": "cool_off", "label": "Take space, then discuss"},
            {"value": "avoid",    "label": "Let things settle on their own"},
            {"value": "mixed",    "label": "Depends on the situation"},
        ]
    },

    # ── Deal-breakers ────────────────────────────────────────────────────────
    {
        "id": "q_db_smoking", "section": "Deal-breakers",
        "text": "Is smoking a deal-breaker?",
        "type": "boolean", "field": "dealbreaker_smoking", "options": None
    },
    {
        "id": "q_db_drugs", "section": "Deal-breakers",
        "text": "Is recreational drug use a deal-breaker?",
        "type": "boolean", "field": "dealbreaker_drugs", "options": None
    },
    {
        "id": "q_db_drinking", "section": "Deal-breakers",
        "text": "Is heavy drinking a deal-breaker?",
        "type": "boolean", "field": "dealbreaker_drinking", "options": None
    },
    {
        "id": "q_db_religion", "section": "Deal-breakers",
        "text": "Is a very different religious background a deal-breaker?",
        "type": "boolean", "field": "dealbreaker_diff_religion", "options": None
    },
    {
        "id": "q_db_politics", "section": "Deal-breakers",
        "text": "Is a very different political outlook a deal-breaker?",
        "type": "boolean", "field": "dealbreaker_diff_politics", "options": None
    },
    {
        "id": "q_db_children", "section": "Deal-breakers",
        "text": "Is a partner not wanting children a deal-breaker?",
        "type": "boolean", "field": "dealbreaker_no_children", "options": None
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_current_user(decoded_token: dict, db: AsyncSession) -> User:
    result = await db.execute(
        select(User).where(User.firebase_uid == decoded_token["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/questions", response_model=List[QuestionMeta])
async def get_questions():
    """Return the full question list for the iOS questionnaire UI."""
    return [QuestionMeta(**q) for q in QUESTIONS]


@router.get("/me")
async def get_my_values(
    decoded_token: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's questionnaire answers, or null if not submitted."""
    user = await _get_current_user(decoded_token, db)

    result = await db.execute(
        select(UserValues).where(UserValues.user_id == user.id)
    )
    uv = result.scalar_one_or_none()
    if not uv:
        return {"completed": False, "values": None}

    return {
        "completed": True,
        "values": ValuesResponse(
            relationship_goal          = uv.relationship_goal,
            wants_children             = uv.wants_children,
            children_timeline_years    = uv.children_timeline_years,
            activity_level             = uv.activity_level,
            social_energy              = uv.social_energy,
            night_owl_score            = uv.night_owl_score,
            travel_importance          = uv.travel_importance,
            religious_importance       = uv.religious_importance,
            religion                   = uv.religion,
            political_leaning          = uv.political_leaning,
            financial_priority         = uv.financial_priority,
            career_ambition            = uv.career_ambition,
            environmental_concern      = uv.environmental_concern,
            big5_openness              = uv.big5_openness,
            big5_conscientiousness     = uv.big5_conscientiousness,
            big5_extraversion          = uv.big5_extraversion,
            big5_agreeableness         = uv.big5_agreeableness,
            big5_neuroticism           = uv.big5_neuroticism,
            communication_directness   = uv.communication_directness,
            conflict_style             = uv.conflict_style,
            dealbreaker_smoking        = uv.dealbreaker_smoking or False,
            dealbreaker_drugs          = uv.dealbreaker_drugs or False,
            dealbreaker_drinking       = uv.dealbreaker_drinking or False,
            dealbreaker_diff_religion  = uv.dealbreaker_diff_religion or False,
            dealbreaker_diff_politics  = uv.dealbreaker_diff_politics or False,
            dealbreaker_no_children    = uv.dealbreaker_no_children or False,
            completed_at               = uv.completed_at,
            updated_at                 = uv.updated_at,
        )
    }


@router.post("/me", status_code=200)
async def submit_values(
    body: ValuesSubmission,
    decoded_token: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
):
    """Submit or update the user's questionnaire answers.
    Triggers an immediate feature vector recompute."""
    user = await _get_current_user(decoded_token, db)

    result = await db.execute(
        select(UserValues).where(UserValues.user_id == user.id)
    )
    uv = result.scalar_one_or_none()

    data = body.model_dump()

    if uv:
        for field, value in data.items():
            setattr(uv, field, value)
        uv.updated_at = datetime.now(timezone.utc)
    else:
        uv = UserValues(user_id=user.id, **data)
        db.add(uv)

    await db.flush()

    # Immediately recompute feature vector so ranking is fresh
    try:
        await upsert_feature_vector(user.id, db)
    except Exception as exc:
        logger.warning(f"Feature vector recompute failed after questionnaire submit: {exc}")

    await db.commit()

    return {
        "message":   "Values saved successfully",
        "user_id":   user.id,
        "completed": True,
    }
