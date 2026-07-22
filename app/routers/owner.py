from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, insert, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import auth_user, owner_only, require_roles
from ..db import get_db
from ..models import (
    Ad,
    AdTariff,
    AuditLog,
    Broadcast,
    Clan,
    ClanApplication,
    ClanInvite,
    ClanMember,
    Notification,
    Payment,
    PlayerProfile,
    Report,
    Room,
    RoomMember,
    User,
)
from ..schemas import (
    AdTariffIn,
    BroadcastIn,
    ClanModerationIn,
    ModerateIn,
    OwnerUserActionIn,
    OwnerUserUpdateIn,
    RefundIn,
    RoomModerationIn,
)

router = APIRouter(prefix="/owner", tags=["owner"], dependencies=[Depends(owner_only)])


def model_dict(value) -> dict:
    return {column.name: getattr(value, column.name) for column in value.__table__.columns}


def log_details(**values) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str)


async def count_rows(db: AsyncSession, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    for condition in conditions:
        statement = statement.where(condition)
    return int((await db.execute(statement)).scalar_one())


def ensure_target_editable(actor: User, target: User) -> None:
    if target.role == "owner" and actor.id != target.id:
        raise HTTPException(403, "Учётную запись владельца нельзя изменять")
    if actor.role == "moderator" and target.role in {"owner", "admin", "moderator"}:
        raise HTTPException(403, "Модератор не может изменять сотрудников")
    if actor.role == "admin" and target.role in {"owner", "admin"} and target.id != actor.id:
        raise HTTPException(403, "Администратор не может изменять владельца или другого администратора")


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_roles(user, "owner", "admin", "moderator")
    now = datetime.utcnow()
    return {
        "users": await count_rows(db, User),
        "new_users_7d": await count_rows(db, User, User.created_at >= now - timedelta(days=7)),
        "banned": await count_rows(db, User, User.is_banned.is_(True)),
        "muted": await count_rows(db, User, User.is_muted.is_(True)),
        "ads_blocked": await count_rows(db, User, User.ads_blocked.is_(True)),
        "rooms": await count_rows(db, Room),
        "rooms_open": await count_rows(db, Room, Room.status == "open"),
        "rooms_blocked": await count_rows(db, Room, Room.status == "blocked"),
        "clans": await count_rows(db, Clan),
        "clans_active": await count_rows(db, Clan, Clan.status == "active"),
        "clans_blocked": await count_rows(db, Clan, Clan.status == "blocked"),
        "ads_pending": await count_rows(db, Ad, Ad.status == "pending_moderation"),
        "payments_paid": await count_rows(db, Payment, Payment.status == "paid"),
        "stars_received": int((await db.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status.in_(["paid", "refunded"])))).scalar_one()),
        "stars_refunded": int((await db.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == "refunded"))).scalar_one()),
        "reports_open": await count_rows(db, Report, Report.status == "open"),
        "broadcasts": await count_rows(db, Broadcast),
    }


@router.get("/statistics")
async def statistics(
    days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    start = datetime.utcnow() - timedelta(days=days - 1)

    async def daily_counts(model) -> dict[str, int]:
        date_expression = func.date(model.created_at)
        rows = (
            await db.execute(
                select(date_expression, func.count())
                .where(model.created_at >= start)
                .group_by(date_expression)
            )
        ).all()
        return {str(day): int(total) for day, total in rows}

    series = {name: await daily_counts(model) for name, model in {
        "users": User,
        "rooms": Room,
        "clans": Clan,
        "ads": Ad,
        "reports": Report,
    }.items()}
    timeline = []
    for offset in range(days):
        day = (start.date() + timedelta(days=offset)).isoformat()
        timeline.append({"date": day, **{name: values.get(day, 0) for name, values in series.items()}})

    member_counts = (
        select(ClanMember.clan_id, func.count().label("members"))
        .where(ClanMember.status == "accepted")
        .group_by(ClanMember.clan_id)
        .subquery()
    )
    top_rows = (
        await db.execute(
            select(Clan, func.coalesce(member_counts.c.members, 0))
            .outerjoin(member_counts, member_counts.c.clan_id == Clan.id)
            .where(Clan.status == "active")
            .order_by(Clan.rating_points.desc(), func.coalesce(member_counts.c.members, 0).desc())
            .limit(10)
        )
    ).all()
    role_rows = (await db.execute(select(User.role, func.count()).group_by(User.role))).all()
    return {
        "days": days,
        "timeline": timeline,
        "roles": {role: int(total) for role, total in role_rows},
        "rooms_by_status": {
            status: await count_rows(db, Room, Room.status == status)
            for status in ["open", "full", "closed", "blocked"]
        },
        "clans_by_status": {
            status: await count_rows(db, Clan, Clan.status == status)
            for status in ["active", "blocked", "closed"]
        },
        "ads_by_status": {
            status: await count_rows(db, Ad, Ad.status == status)
            for status in ["draft", "awaiting_payment", "pending_moderation", "active", "rejected", "expired", "refunded"]
        },
        "top_clans": [
            {
                "id": clan.id,
                "name": clan.name,
                "tag": clan.tag,
                "rating_points": clan.rating_points,
                "members_count": int(members),
            }
            for clan, members in top_rows
        ],
    }


@router.get("/users")
async def users(
    query: str | None = Query(default=None, max_length=100),
    role: str | None = Query(default=None, max_length=20),
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    filters = []
    if query:
        term = query.strip().lstrip("@")
        text_condition = or_(
            User.username.ilike(f"%{term}%"),
            User.display_name.ilike(f"%{term}%"),
            PlayerProfile.nickname.ilike(f"%{term}%"),
            PlayerProfile.pubg_id.ilike(f"%{term}%"),
        )
        if term.isdigit():
            numeric = int(term)
            text_condition = or_(text_condition, User.id == numeric, User.telegram_id == numeric)
        filters.append(text_condition)
    if role:
        filters.append(User.role == role)
    now = datetime.utcnow()
    if status == "banned":
        filters.append(User.is_banned.is_(True))
    elif status == "muted":
        filters.append(User.is_muted.is_(True))
    elif status == "ads_blocked":
        filters.append(User.ads_blocked.is_(True))
    elif status == "online":
        filters.append(User.last_seen_at >= now - timedelta(minutes=10))
    elif status == "active":
        filters.append(User.is_banned.is_(False))

    base = select(User, PlayerProfile).outerjoin(PlayerProfile, PlayerProfile.user_id == User.id)
    total_statement = select(func.count(func.distinct(User.id))).select_from(User).outerjoin(
        PlayerProfile, PlayerProfile.user_id == User.id
    )
    for condition in filters:
        base = base.where(condition)
        total_statement = total_statement.where(condition)
    total = int((await db.execute(total_statement)).scalar_one())
    rows = (await db.execute(base.order_by(User.id.desc()).offset(offset).limit(limit))).all()
    items = []
    for target, profile in rows:
        clan_row = (
            await db.execute(
                select(Clan.id, Clan.name, Clan.tag, ClanMember.role)
                .join(ClanMember, ClanMember.clan_id == Clan.id)
                .where(
                    ClanMember.user_id == target.id,
                    ClanMember.status == "accepted",
                    Clan.status == "active",
                )
                .limit(1)
            )
        ).first()
        items.append({
            "id": target.id,
            "telegram_id": target.telegram_id,
            "username": target.username,
            "display_name": target.display_name,
            "role": target.role,
            "is_banned": target.is_banned,
            "is_muted": target.is_muted,
            "mute_until": target.mute_until,
            "ads_blocked": target.ads_blocked,
            "last_seen_at": target.last_seen_at,
            "created_at": target.created_at,
            "nickname": profile.nickname if profile else "",
            "pubg_id": profile.pubg_id if profile else "",
            "server": profile.server if profile else "",
            "rank": profile.rank if profile else "",
            "clan": None if not clan_row else {
                "id": clan_row.id, "name": clan_row.name, "tag": clan_row.tag, "role": clan_row.role
            },
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/users/{user_id}")
async def user_detail(user_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_roles(user, "owner", "admin", "moderator")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Пользователь не найден")
    profile = (
        await db.execute(select(PlayerProfile).where(PlayerProfile.user_id == target.id))
    ).scalar_one_or_none()
    clan = (
        await db.execute(
            select(Clan, ClanMember)
            .join(ClanMember, ClanMember.clan_id == Clan.id)
            .where(ClanMember.user_id == target.id, ClanMember.status == "accepted", Clan.status == "active")
            .limit(1)
        )
    ).first()
    rooms = (await db.execute(select(Room).where(Room.owner_id == target.id).order_by(Room.id.desc()).limit(20))).scalars().all()
    ads = (await db.execute(select(Ad).where(Ad.user_id == target.id).order_by(Ad.id.desc()).limit(20))).scalars().all()
    report_conditions = [Report.target_kind == "user", Report.target_id == target.id]
    if profile:
        report_conditions.append(or_(Report.target_kind != "profile", Report.target_id == profile.id))
    reports = (
        await db.execute(
            select(Report)
            .where(or_(
                (Report.target_kind == "user") & (Report.target_id == target.id),
                (Report.target_kind == "profile") & (Report.target_id == (profile.id if profile else -1)),
            ))
            .order_by(Report.id.desc()).limit(30)
        )
    ).scalars().all()
    audit = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.object_kind == "user", AuditLog.object_id == target.id)
            .order_by(AuditLog.id.desc()).limit(30)
        )
    ).scalars().all()
    return {
        "user": model_dict(target),
        "profile": model_dict(profile) if profile else None,
        "clan": None if not clan else {"clan": model_dict(clan[0]), "membership": model_dict(clan[1])},
        "rooms": [model_dict(item) for item in rooms],
        "ads": [model_dict(item) for item in ads],
        "reports": [model_dict(item) for item in reports],
        "audit": [model_dict(item) for item in audit],
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    payload: OwnerUserUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Пользователь не найден")
    ensure_target_editable(user, target)
    changes = payload.model_dump(exclude_unset=True)
    user_fields = {"display_name", "username", "moderation_note"}
    for field in user_fields:
        if field in changes:
            setattr(target, field, changes.pop(field))
    profile = (
        await db.execute(select(PlayerProfile).where(PlayerProfile.user_id == target.id))
    ).scalar_one_or_none()
    profile_map = {"player_role": "role"}
    if changes and not profile:
        raise HTTPException(409, "У пользователя ещё нет игровой анкеты")
    for field, value in changes.items():
        setattr(profile, profile_map.get(field, field), value)
    db.add(AuditLog(
        actor_id=user.id,
        action="user.update",
        object_kind="user",
        object_id=target.id,
        details=log_details(fields=sorted(payload.model_dump(exclude_unset=True))),
    ))
    await db.commit()
    return await user_detail(user_id, db, user)


@router.post("/users/{user_id}/actions")
async def user_action(
    user_id: int,
    payload: OwnerUserActionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Пользователь не найден")
    ensure_target_editable(user, target)
    if user.id == target.id and payload.action in {"ban", "mute", "block_ads", "set_role"}:
        raise HTTPException(400, "Нельзя применить это действие к своей учётной записи")
    if user.role == "moderator" and payload.action not in {"mute", "unmute"}:
        raise HTTPException(403, "Модератор может только выдавать и снимать мут")
    if payload.action == "set_role" and user.role != "owner":
        raise HTTPException(403, "Роли сотрудников изменяет только владелец")

    now = datetime.utcnow()
    if payload.action == "ban":
        target.is_banned = True
        target.ban_reason = payload.reason or "Нарушение правил"
        await db.execute(update(Room).where(
            Room.owner_id == target.id, Room.status.in_(["open", "full"])
        ).values(status="blocked", moderation_reason=target.ban_reason))
        await db.execute(update(Clan).where(
            Clan.owner_id == target.id, Clan.status == "active"
        ).values(status="blocked", recruitment_open=False, blocked_reason=target.ban_reason))
        await db.execute(update(Ad).where(
            Ad.user_id == target.id, Ad.status.in_(["draft", "pending_moderation", "active"])
        ).values(status="rejected", rejection_reason=target.ban_reason))
    elif payload.action == "unban":
        target.is_banned = False
        target.ban_reason = ""
    elif payload.action == "mute":
        target.is_muted = True
        target.mute_until = now + timedelta(hours=payload.duration_hours or 24)
    elif payload.action == "unmute":
        target.is_muted = False
        target.mute_until = None
    elif payload.action == "block_ads":
        target.ads_blocked = True
    elif payload.action == "unblock_ads":
        target.ads_blocked = False
    elif payload.action == "set_role":
        if not payload.role:
            raise HTTPException(400, "Не указана новая роль")
        target.role = payload.role

    db.add(Notification(
        user_id=target.id,
        kind="moderation",
        title="Изменение доступа",
        text=f"Действие: {payload.action}. {payload.reason}".strip(),
    ))
    db.add(AuditLog(
        actor_id=user.id,
        action=f"user.{payload.action}",
        object_kind="user",
        object_id=target.id,
        details=log_details(reason=payload.reason, duration_hours=payload.duration_hours, role=payload.role),
    ))
    await db.commit()
    return {
        "id": target.id,
        "role": target.role,
        "is_banned": target.is_banned,
        "is_muted": target.is_muted,
        "mute_until": target.mute_until,
        "ads_blocked": target.ads_blocked,
    }


@router.post("/users/{user_id}")
async def moderate_user_legacy(
    user_id: int,
    payload: ModerateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    if payload.decision not in {"ban", "unban"}:
        raise HTTPException(400, "Для пользователя допустимы ban/unban")
    return await user_action(
        user_id,
        OwnerUserActionIn(action=payload.decision, reason=payload.reason),
        db,
        user,
    )


@router.get("/rooms")
async def rooms(
    query: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    members = (
        select(RoomMember.room_id, func.count().label("members"))
        .where(RoomMember.status == "accepted")
        .group_by(RoomMember.room_id)
        .subquery()
    )
    statement = (
        select(Room, User, func.coalesce(members.c.members, 0))
        .join(User, User.id == Room.owner_id)
        .outerjoin(members, members.c.room_id == Room.id)
    )
    if query:
        term = query.strip().lstrip("@")
        condition = or_(Room.title.ilike(f"%{term}%"), User.username.ilike(f"%{term}%"), User.display_name.ilike(f"%{term}%"))
        if term.isdigit():
            condition = or_(condition, Room.id == int(term), User.id == int(term), User.telegram_id == int(term))
        statement = statement.where(condition)
    if status:
        statement = statement.where(Room.status == status)
    rows = (await db.execute(statement.order_by(Room.id.desc()).limit(limit))).all()
    return [{
        **model_dict(room),
        "members_count": int(member_count),
        "owner": {"id": owner.id, "display_name": owner.display_name, "username": owner.username},
    } for room, owner, member_count in rows]


@router.post("/rooms/{room_id}")
async def moderate_room(
    room_id: int,
    payload: RoomModerationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(404, "Комната не найдена")
    if payload.decision == "close":
        room.status = "closed"
    elif payload.decision == "block":
        room.status = "blocked"
    elif payload.decision == "reopen":
        accepted = await count_rows(db, RoomMember, RoomMember.room_id == room.id, RoomMember.status == "accepted")
        room.status = "full" if accepted >= room.slots_total else "open"
    room.moderation_reason = "" if payload.decision == "reopen" else payload.reason
    db.add(Notification(
        user_id=room.owner_id,
        kind="room_moderation",
        title="Решение по комнате",
        text=f"Комната «{room.title}»: {room.status}. {payload.reason}".strip(),
    ))
    db.add(AuditLog(
        actor_id=user.id,
        action=f"room.moderation.{payload.decision}",
        object_kind="room",
        object_id=room.id,
        details=payload.reason,
    ))
    await db.commit()
    return {"id": room.id, "status": room.status, "reason": room.moderation_reason}


@router.get("/reports")
async def reports(
    status: str | None = Query(default=None, max_length=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    statement = select(Report).order_by(Report.id.desc()).limit(300)
    if status:
        statement = statement.where(Report.status == status)
    rows = (await db.execute(statement)).scalars().all()
    return [model_dict(item) for item in rows]


@router.post("/reports/{report_id}")
async def moderate_report(
    report_id: int,
    payload: ModerateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Жалоба не найдена")
    report.status = "closed"
    report.resolution = payload.reason
    db.add(AuditLog(
        actor_id=user.id,
        action="report.close",
        object_kind="report",
        object_id=report.id,
        details=payload.reason,
    ))
    await db.commit()
    return {"ok": True}


@router.get("/ads")
async def ads(
    status: str | None = Query(default=None, max_length=30),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    statement = select(Ad, User).join(User, User.id == Ad.user_id).order_by(Ad.id.desc()).limit(300)
    if status:
        statement = statement.where(Ad.status == status)
    rows = (await db.execute(statement)).all()
    return [{
        **model_dict(ad),
        "owner": {"id": owner.id, "display_name": owner.display_name, "username": owner.username},
    } for ad, owner in rows]


@router.post("/ads/{ad_id}")
async def moderate_ad(
    ad_id: int,
    payload: ModerateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    ad = await db.get(Ad, ad_id)
    if not ad:
        raise HTTPException(404, "Реклама не найдена")
    if ad.status != "pending_moderation":
        raise HTTPException(409, "Объявление не находится на модерации")
    if payload.decision == "approve":
        if not ad.paid_at or not ad.telegram_payment_charge_id:
            raise HTTPException(409, "Оплата Telegram Stars не подтверждена")
        ad.status = "active"
        ad.starts_at = datetime.utcnow()
        ad.ends_at = ad.starts_at + timedelta(days=ad.duration_days)
        ad.rejection_reason = ""
    elif payload.decision == "reject":
        ad.status = "rejected"
        ad.rejection_reason = payload.reason
    else:
        raise HTTPException(400, "Для рекламы допустимы approve/reject")
    db.add(Notification(
        user_id=ad.user_id,
        kind="ad_moderation",
        title="Решение по рекламе",
        text=f"Статус объявления «{ad.title}»: {ad.status}. {payload.reason}".strip(),
    ))
    db.add(AuditLog(
        actor_id=user.id,
        action=f"ad.{payload.decision}",
        object_kind="ad",
        object_id=ad.id,
        details=payload.reason,
    ))
    await db.commit()
    return {"status": ad.status}


@router.get("/clans")
async def clans(
    query: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    statement = select(Clan).order_by(Clan.id.desc()).limit(300)
    if query:
        term = query.strip()
        condition = or_(Clan.name.ilike(f"%{term}%"), Clan.tag.ilike(f"%{term}%"))
        if term.isdigit():
            condition = or_(condition, Clan.id == int(term), Clan.owner_id == int(term))
        statement = statement.where(condition)
    if status:
        statement = statement.where(Clan.status == status)
    rows = (await db.execute(statement)).scalars().all()
    result = []
    for clan in rows:
        members = await count_rows(db, ClanMember, ClanMember.clan_id == clan.id, ClanMember.status == "accepted")
        open_reports = await count_rows(
            db, Report, Report.target_kind == "clan", Report.target_id == clan.id, Report.status == "open"
        )
        result.append({
            "id": clan.id,
            "name": clan.name,
            "tag": clan.tag,
            "owner_id": clan.owner_id,
            "server": clan.server,
            "members_count": members,
            "max_members": clan.max_members,
            "recruitment_open": clan.recruitment_open,
            "status": clan.status,
            "blocked_reason": clan.blocked_reason,
            "open_reports": open_reports,
            "created_at": clan.created_at,
        })
    return result


@router.post("/clans/{clan_id}")
async def moderate_clan(
    clan_id: int,
    payload: ClanModerationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    clan = await db.get(Clan, clan_id)
    if not clan:
        raise HTTPException(404, "Клан не найден")
    if payload.decision == "block":
        clan.status = "blocked"
        clan.recruitment_open = False
        clan.blocked_reason = payload.reason or "Заблокирован модерацией"
        await db.execute(update(ClanApplication).where(
            ClanApplication.clan_id == clan.id, ClanApplication.status == "pending"
        ).values(status="cancelled", decided_at=datetime.utcnow(), decision_note="Клан заблокирован"))
        await db.execute(update(ClanInvite).where(
            ClanInvite.clan_id == clan.id, ClanInvite.status == "pending"
        ).values(status="cancelled", decided_at=datetime.utcnow()))
    elif payload.decision == "unblock":
        clan.status = "active"
        clan.blocked_reason = ""
    elif payload.decision == "close":
        clan.status = "closed"
        clan.recruitment_open = False
        clan.blocked_reason = payload.reason
        await db.execute(update(ClanMember).where(
            ClanMember.clan_id == clan.id, ClanMember.status == "accepted"
        ).values(status="left"))
    db.add(Notification(
        user_id=clan.owner_id,
        kind="clan_moderation",
        title="Решение по клану",
        text=f"Статус клана «{clan.name}»: {clan.status}. {payload.reason}".strip(),
    ))
    db.add(AuditLog(
        actor_id=user.id,
        action=f"clan.moderation.{payload.decision}",
        object_kind="clan",
        object_id=clan.id,
        details=payload.reason,
    ))
    await db.commit()
    return {"status": clan.status, "reason": clan.blocked_reason}


@router.get("/broadcasts")
async def broadcasts(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_roles(user, "owner", "admin", "moderator")
    rows = (await db.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(100))).scalars().all()
    return [model_dict(item) for item in rows]


def broadcast_recipient_query(payload: BroadcastIn):
    statement = select(User.id.label("user_id")).where(User.is_banned.is_(False))
    if payload.target == "users":
        statement = statement.where(User.role == "user")
    elif payload.target == "clan_owners":
        statement = statement.where(exists(select(ClanMember.id).where(
            ClanMember.user_id == User.id,
            ClanMember.role == "owner",
            ClanMember.status == "accepted",
        )))
    elif payload.target == "room_owners":
        statement = statement.where(exists(select(Room.id).where(Room.owner_id == User.id)))
    elif payload.target == "staff":
        statement = statement.where(User.role.in_(["owner", "admin", "moderator"]))
    elif payload.target == "active_7d":
        statement = statement.where(User.last_seen_at >= datetime.utcnow() - timedelta(days=7))
    elif payload.target == "active_30d":
        statement = statement.where(User.last_seen_at >= datetime.utcnow() - timedelta(days=30))
    return statement


@router.post("/broadcasts")
async def create_broadcast(
    payload: BroadcastIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin")
    recipients_query = broadcast_recipient_query(payload)
    recipients = recipients_query.subquery()
    total = int((await db.execute(select(func.count()).select_from(recipients))).scalar_one())
    created_at = datetime.utcnow()
    broadcast = Broadcast(
        created_by=user.id,
        target=payload.target,
        title=payload.title,
        text=payload.text,
        recipients_count=total,
        status="sent",
        created_at=created_at,
    )
    db.add(broadcast)
    await db.flush()
    if total:
        notification_rows = select(
            recipients.c.user_id,
            literal("broadcast"),
            literal(payload.title),
            literal(payload.text),
            literal(False),
            literal(created_at),
        )
        await db.execute(insert(Notification).from_select(
            ["user_id", "kind", "title", "text", "is_read", "created_at"],
            notification_rows,
        ))
    db.add(AuditLog(
        actor_id=user.id,
        action="broadcast.send",
        object_kind="broadcast",
        object_id=broadcast.id,
        details=log_details(target=payload.target, recipients=total),
    ))
    await db.commit()
    return {"id": broadcast.id, "status": broadcast.status, "recipients_count": total}


@router.get("/audit")
async def audit(
    action: str | None = Query(default=None, max_length=80),
    object_kind: str | None = Query(default=None, max_length=40),
    actor_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner", "admin", "moderator")
    statement = select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_id)
    if action:
        statement = statement.where(AuditLog.action.ilike(f"%{action}%"))
    if object_kind:
        statement = statement.where(AuditLog.object_kind == object_kind)
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    rows = (await db.execute(statement.order_by(AuditLog.id.desc()).limit(limit))).all()
    return [{
        **model_dict(item),
        "actor": None if not actor else {
            "id": actor.id,
            "display_name": actor.display_name,
            "username": actor.username,
            "role": actor.role,
        },
    } for item, actor in rows]


@router.get("/tariffs")
async def owner_tariffs(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_roles(user, "owner")
    rows = (await db.execute(select(AdTariff).order_by(AdTariff.id.asc()))).scalars().all()
    return [model_dict(item) for item in rows]


@router.post("/tariffs")
async def create_tariff(
    payload: AdTariffIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner")
    exists_row = (
        await db.execute(select(AdTariff).where(func.lower(AdTariff.name) == payload.name.lower()))
    ).scalar_one_or_none()
    if exists_row:
        raise HTTPException(409, "Тариф с таким названием уже существует")
    tariff = AdTariff(**payload.model_dump())
    db.add(tariff)
    await db.flush()
    db.add(AuditLog(
        actor_id=user.id,
        action="tariff.create",
        object_kind="tariff",
        object_id=tariff.id,
        details=log_details(name=tariff.name, price_stars=tariff.price_stars),
    ))
    await db.commit()
    await db.refresh(tariff)
    return model_dict(tariff)


@router.patch("/tariffs/{tariff_id}")
async def update_tariff(
    tariff_id: int,
    payload: AdTariffIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner")
    tariff = await db.get(AdTariff, tariff_id)
    if not tariff:
        raise HTTPException(404, "Тариф не найден")
    duplicate = (
        await db.execute(select(AdTariff).where(
            func.lower(AdTariff.name) == payload.name.lower(),
            AdTariff.id != tariff.id,
        ))
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(409, "Тариф с таким названием уже существует")
    for field, value in payload.model_dump().items():
        setattr(tariff, field, value)
    db.add(AuditLog(
        actor_id=user.id,
        action="tariff.update",
        object_kind="tariff",
        object_id=tariff.id,
        details=log_details(name=tariff.name, price_stars=tariff.price_stars, active=tariff.is_active),
    ))
    await db.commit()
    return model_dict(tariff)


@router.get("/payments")
async def payments(
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_roles(user, "owner")
    statement = (
        select(Payment, User, Ad, AdTariff)
        .join(User, User.id == Payment.user_id)
        .join(Ad, Ad.id == Payment.ad_id)
        .outerjoin(AdTariff, AdTariff.id == Payment.tariff_id)
        .order_by(Payment.id.desc())
        .limit(limit)
    )
    if status:
        statement = statement.where(Payment.status == status)
    rows = (await db.execute(statement)).all()
    return [{
        **model_dict(payment),
        "user": {"id": payer.id, "telegram_id": payer.telegram_id, "display_name": payer.display_name, "username": payer.username},
        "ad": {"id": ad.id, "title": ad.title, "status": ad.status},
        "tariff": model_dict(tariff) if tariff else None,
    } for payment, payer, ad, tariff in rows]


@router.post("/payments/{payment_id}/refund")
async def refund_payment(
    payment_id: int,
    payload: RefundIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    from ..config import get_settings

    require_roles(user, "owner")
    payment = await db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    if payment.status != "paid" or not payment.telegram_payment_charge_id:
        raise HTTPException(409, "Этот платёж нельзя вернуть")
    payer = await db.get(User, payment.user_id)
    ad = await db.get(Ad, payment.ad_id)
    if not payer or not ad:
        raise HTTPException(409, "Данные платежа повреждены")

    settings = get_settings()
    if settings.bot_token:
        from aiogram import Bot
        bot = Bot(settings.bot_token)
        try:
            ok = await bot.refund_star_payment(
                user_id=payer.telegram_id,
                telegram_payment_charge_id=payment.telegram_payment_charge_id,
            )
            if not ok:
                raise HTTPException(502, "Telegram не подтвердил возврат")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, "Telegram не выполнил возврат Stars") from exc
        finally:
            await bot.session.close()
    elif not settings.allow_dev_auth:
        raise HTTPException(503, "BOT_TOKEN не настроен")

    now = datetime.utcnow()
    payment.status = "refunded"
    payment.refunded_at = now
    payment.refund_reason = payload.reason
    ad.status = "refunded"
    ad.refunded_at = now
    ad.ends_at = now
    db.add(Notification(
        user_id=payer.id,
        kind="refund",
        title="Возврат Telegram Stars",
        text=f"Возвращено {payment.amount} Stars за объявление «{ad.title}». Причина: {payload.reason}",
    ))
    db.add(AuditLog(
        actor_id=user.id,
        action="payment.refund",
        object_kind="payment",
        object_id=payment.id,
        details=log_details(amount=payment.amount, ad_id=ad.id, reason=payload.reason),
    ))
    await db.commit()
    return {"payment_id": payment.id, "status": payment.status, "refunded_at": payment.refunded_at}


@router.get("/system/status")
async def system_status(user: User = Depends(auth_user)):
    from ..config import get_settings
    from ..runtime import runtime_state

    require_roles(user, "owner")
    settings = get_settings()
    return {
        "version": settings.app_version,
        "environment": settings.environment,
        "database_backend": settings.database_url.split(":", 1)[0],
        "telegram_mode": settings.telegram_mode,
        "public_base_url": settings.effective_public_base_url,
        "webhook_path": settings.webhook_path,
        "backup_enabled": settings.backup_enabled,
        "backup_interval_hours": settings.backup_interval_hours,
        "runtime": runtime_state.public_dict(),
    }


@router.post("/system/backup")
async def system_backup(user: User = Depends(auth_user)):
    from pathlib import Path
    from ..backup_service import create_backup

    require_roles(user, "owner")
    try:
        path = await create_backup()
    except Exception as exc:
        raise HTTPException(500, f"Резервная копия не создана: {exc}") from exc
    return {"created": True, "file": Path(path).name}
