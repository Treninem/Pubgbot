from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..auth import auth_user
from ..models import User, PlayerProfile
from ..schemas import ProfileIn

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/mine")
async def mine(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    p = (await db.execute(select(PlayerProfile).where(PlayerProfile.user_id == user.id))).scalar_one_or_none()
    return None if p is None else {c.name: getattr(p, c.name) for c in p.__table__.columns}


@router.put("/mine")
async def upsert(payload: ProfileIn, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    p = (await db.execute(select(PlayerProfile).where(PlayerProfile.user_id == user.id))).scalar_one_or_none()
    if p is None:
        p = PlayerProfile(user_id=user.id, **payload.model_dump())
        db.add(p)
    else:
        for k, v in payload.model_dump().items():
            setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return {c.name: getattr(p, c.name) for c in p.__table__.columns}


@router.get("")
async def search_profiles(
    server: str | None = None, role: str | None = None, rank: str | None = None,
    has_mic: bool | None = None, q: str | None = Query(default=None, max_length=60),
    db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)
):
    stmt = select(PlayerProfile, User).join(User, User.id == PlayerProfile.user_id).where(
        PlayerProfile.is_visible == True, PlayerProfile.user_id != user.id, User.is_banned == False
    )
    if server: stmt = stmt.where(PlayerProfile.server == server)
    if role: stmt = stmt.where(PlayerProfile.role == role)
    if rank: stmt = stmt.where(PlayerProfile.rank.ilike(f"%{rank}%"))
    if has_mic is not None: stmt = stmt.where(PlayerProfile.has_mic == has_mic)
    if q: stmt = stmt.where(PlayerProfile.nickname.ilike(f"%{q}%"))
    rows = (await db.execute(stmt.limit(100))).all()
    return [{
        "id": p.id, "user_id": u.id, "nickname": p.nickname, "pubg_id": p.pubg_id,
        "server": p.server, "rank": p.rank, "role": p.role, "has_mic": p.has_mic,
        "play_time": p.play_time, "about": p.about, "looking_for_team": p.looking_for_team
    } for p, u in rows]
