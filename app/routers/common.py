from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..auth import auth_user, is_exact_owner
from ..models import User, PlayerProfile, Room, Clan, Ad, Report, Notification

router = APIRouter(tags=["common"])


@router.get("/me")
async def me(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    return {
        "id": user.id, "telegram_id": user.telegram_id, "username": user.username,
        "display_name": user.display_name, "role": user.role,
        "is_owner": is_exact_owner(user),
        "is_muted": user.is_muted, "mute_until": user.mute_until,
        "ads_blocked": user.ads_blocked, "last_seen_at": user.last_seen_at
    }


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    async def count(model, *conditions):
        q = select(func.count()).select_from(model)
        for cond in conditions:
            q = q.where(cond)
        return int((await db.execute(q)).scalar_one())
    return {
        "users": await count(User),
        "profiles": await count(PlayerProfile, PlayerProfile.is_visible == True),
        "active_rooms": await count(Room, Room.status == "open"),
        "clans": await count(Clan, Clan.status == "active"),
        "active_ads": await count(Ad, Ad.status == "active"),
        "open_reports": await count(Report, Report.status == "open"),
    }


@router.get("/notifications")
async def notifications(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    rows = (await db.execute(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.id.desc()).limit(100)
    )).scalars().all()
    return [{"id": x.id, "kind": x.kind, "title": x.title, "text": x.text,
             "is_read": x.is_read, "created_at": x.created_at} for x in rows]
