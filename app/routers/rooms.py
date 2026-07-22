from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..auth import auth_user, require_not_muted
from ..models import User, Room, RoomMember, Notification
from ..schemas import RoomIn

router = APIRouter(prefix="/rooms", tags=["rooms"])


async def room_payload(db, room):
    count = int((await db.execute(select(func.count()).select_from(RoomMember).where(
        RoomMember.room_id == room.id, RoomMember.status == "accepted"
    ))).scalar_one())
    return {**{c.name: getattr(room, c.name) for c in room.__table__.columns}, "members_count": count}


@router.get("")
async def list_rooms(server: str | None = None, mode: str | None = None,
                     db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    stmt = select(Room).where(Room.status == "open").order_by(Room.id.desc())
    if server: stmt = stmt.where(Room.server == server)
    if mode: stmt = stmt.where(Room.mode == mode)
    rooms = (await db.execute(stmt.limit(100))).scalars().all()
    return [await room_payload(db, x) for x in rooms]


@router.post("")
async def create_room(payload: RoomIn, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_not_muted(user)
    room = Room(owner_id=user.id, **payload.model_dump())
    db.add(room); await db.flush()
    db.add(RoomMember(room_id=room.id, user_id=user.id, status="accepted"))
    await db.commit(); await db.refresh(room)
    return await room_payload(db, room)


@router.post("/{room_id}/join")
async def join(room_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_not_muted(user)
    room = await db.get(Room, room_id)
    if not room or room.status != "open": raise HTTPException(404, "Комната недоступна")
    existing = (await db.execute(select(RoomMember).where(
        RoomMember.room_id == room_id, RoomMember.user_id == user.id
    ))).scalar_one_or_none()
    if existing: return {"status": existing.status}
    accepted = int((await db.execute(select(func.count()).select_from(RoomMember).where(
        RoomMember.room_id == room_id, RoomMember.status == "accepted"
    ))).scalar_one())
    status = "accepted" if accepted < room.slots_total else "pending"
    db.add(RoomMember(room_id=room_id, user_id=user.id, status=status))
    db.add(Notification(user_id=room.owner_id, kind="room_join", title="Новый участник",
                        text=f"Игрок подал заявку или вступил в комнату «{room.title}»."))
    if status == "accepted" and accepted + 1 >= room.slots_total:
        room.status = "full"
    await db.commit()
    return {"status": status}


@router.post("/{room_id}/leave")
async def leave(room_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    member = (await db.execute(select(RoomMember).where(
        RoomMember.room_id == room_id, RoomMember.user_id == user.id
    ))).scalar_one_or_none()
    if not member: raise HTTPException(404, "Участие не найдено")
    await db.delete(member)
    room = await db.get(Room, room_id)
    if room and room.status == "full": room.status = "open"
    await db.commit()
    return {"ok": True}


@router.post("/{room_id}/close")
async def close(room_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    room = await db.get(Room, room_id)
    if not room or room.owner_id != user.id: raise HTTPException(403, "Только владелец комнаты")
    room.status = "closed"; await db.commit()
    return {"ok": True}
