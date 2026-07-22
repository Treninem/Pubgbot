from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..auth import auth_user, require_not_muted
from ..models import User, Invitation, Favorite, Report, Notification
from ..schemas import InvitationIn, ReportIn

router = APIRouter(tags=["social"])


@router.post("/invitations")
async def invite(payload: InvitationIn, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_not_muted(user)
    if payload.recipient_id == user.id: raise HTTPException(400, "Нельзя пригласить себя")
    inv = Invitation(sender_id=user.id, **payload.model_dump())
    db.add(inv)
    db.add(Notification(user_id=payload.recipient_id, kind="invitation",
                        title="Новое приглашение", text=payload.message or "Вам отправили приглашение."))
    await db.commit(); await db.refresh(inv)
    return {"id": inv.id, "status": inv.status}


@router.get("/invitations")
async def invitations(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    rows = (await db.execute(select(Invitation).where(
        (Invitation.recipient_id == user.id) | (Invitation.sender_id == user.id)
    ).order_by(Invitation.id.desc()).limit(100))).scalars().all()
    return [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in rows]


@router.post("/invitations/{invitation_id}/{decision}")
async def decide(invitation_id: int, decision: str, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    if decision not in {"accept","reject","cancel"}: raise HTTPException(400, "Неверное решение")
    inv = await db.get(Invitation, invitation_id)
    if not inv: raise HTTPException(404, "Приглашение не найдено")
    if decision == "cancel" and inv.sender_id != user.id: raise HTTPException(403)
    if decision != "cancel" and inv.recipient_id != user.id: raise HTTPException(403)
    inv.status = {"accept":"accepted","reject":"rejected","cancel":"cancelled"}[decision]
    await db.commit()
    return {"status": inv.status}


@router.post("/favorites/{kind}/{target_id}")
async def toggle_favorite(kind: str, target_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    fav = (await db.execute(select(Favorite).where(
        Favorite.user_id == user.id, Favorite.kind == kind, Favorite.target_id == target_id
    ))).scalar_one_or_none()
    if fav:
        await db.delete(fav); active = False
    else:
        db.add(Favorite(user_id=user.id, kind=kind, target_id=target_id)); active = True
    await db.commit()
    return {"active": active}


@router.post("/reports")
async def report(payload: ReportIn, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_not_muted(user)
    item = Report(reporter_id=user.id, **payload.model_dump())
    db.add(item); await db.commit(); await db.refresh(item)
    return {"id": item.id, "status": item.status}
