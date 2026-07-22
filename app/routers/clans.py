from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import auth_user, require_not_muted
from ..config import get_settings
from ..db import get_db
from ..models import (
    AuditLog,
    Clan,
    ClanApplication,
    ClanInvite,
    ClanMember,
    Notification,
    PlayerProfile,
    User,
)
from ..schemas import (
    ClanApplicationIn,
    ClanDecisionIn,
    ClanIn,
    ClanInviteDecisionIn,
    ClanInviteIn,
    ClanRecruitmentIn,
    ClanRoleIn,
    ClanTransferIn,
    ClanUpdateIn,
)

router = APIRouter(prefix="/clans", tags=["clans"])
settings = get_settings()


def log_details(**values) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


async def accepted_member(db: AsyncSession, clan_id: int, user_id: int) -> ClanMember | None:
    return (
        await db.execute(
            select(ClanMember).where(
                ClanMember.clan_id == clan_id,
                ClanMember.user_id == user_id,
                ClanMember.status == "accepted",
            )
        )
    ).scalar_one_or_none()


async def active_membership(db: AsyncSession, user_id: int) -> tuple[ClanMember, Clan] | None:
    return (
        await db.execute(
            select(ClanMember, Clan)
            .join(Clan, Clan.id == ClanMember.clan_id)
            .where(
                ClanMember.user_id == user_id,
                ClanMember.status == "accepted",
                Clan.status == "active",
            )
            .limit(1)
        )
    ).first()


async def require_clan(db: AsyncSession, clan_id: int, allow_blocked: bool = False) -> Clan:
    clan = await db.get(Clan, clan_id)
    if not clan or (not allow_blocked and clan.status != "active"):
        raise HTTPException(404, "Клан не найден или недоступен")
    return clan


async def require_manager(db: AsyncSession, clan_id: int, user: User, owner_only: bool = False) -> tuple[Clan, ClanMember]:
    clan = await require_clan(db, clan_id)
    member = await accepted_member(db, clan_id, user.id)
    allowed = {"owner"} if owner_only else {"owner", "officer"}
    if not member or member.role not in allowed:
        raise HTTPException(403, "Недостаточно прав в клане")
    return clan, member


async def members_count(db: AsyncSession, clan_id: int) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(ClanMember)
                .where(ClanMember.clan_id == clan_id, ClanMember.status == "accepted")
            )
        ).scalar_one()
    )


async def clan_payload(db: AsyncSession, clan: Clan, user: User | None = None) -> dict:
    accepted = await members_count(db, clan.id)
    officers = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ClanMember)
                .where(
                    ClanMember.clan_id == clan.id,
                    ClanMember.status == "accepted",
                    ClanMember.role == "officer",
                )
            )
        ).scalar_one()
    )
    current_member = await accepted_member(db, clan.id, user.id) if user else None
    application = None
    if user and not current_member:
        application = (
            await db.execute(
                select(ClanApplication)
                .where(
                    ClanApplication.clan_id == clan.id,
                    ClanApplication.applicant_id == user.id,
                )
                .order_by(ClanApplication.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    rating_score = clan.rating_points + accepted * 25 + officers * 10
    data = {column.name: getattr(clan, column.name) for column in clan.__table__.columns}
    data.update(
        {
            "members_count": accepted,
            "officers_count": officers,
            "rating_score": rating_score,
            "is_full": accepted >= clan.max_members,
            "my_role": current_member.role if current_member else None,
            "my_membership": current_member.status if current_member else None,
            "my_application": application.status if application else None,
            "can_manage": bool(current_member and current_member.role in {"owner", "officer"}),
            "is_owner": bool(current_member and current_member.role == "owner"),
        }
    )
    return data


async def member_rows(db: AsyncSession, clan_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(ClanMember, User, PlayerProfile)
            .join(User, User.id == ClanMember.user_id)
            .outerjoin(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(ClanMember.clan_id == clan_id, ClanMember.status == "accepted")
            .order_by(ClanMember.id.asc())
        )
    ).all()
    role_order = {"owner": 0, "officer": 1, "member": 2}
    result = []
    for member, account, profile in rows:
        result.append(
            {
                "user_id": account.id,
                "telegram_id": account.telegram_id,
                "username": account.username,
                "display_name": account.display_name,
                "nickname": profile.nickname if profile else account.display_name,
                "pubg_id": profile.pubg_id if profile else "",
                "rank": profile.rank if profile else "",
                "has_mic": profile.has_mic if profile else False,
                "role": member.role,
                "joined_at": member.created_at,
            }
        )
    return sorted(result, key=lambda item: (role_order.get(item["role"], 9), item["nickname"].lower()))


async def application_rows(db: AsyncSession, clan_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(ClanApplication, User, PlayerProfile)
            .join(User, User.id == ClanApplication.applicant_id)
            .outerjoin(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(ClanApplication.clan_id == clan_id, ClanApplication.status == "pending")
            .order_by(ClanApplication.id.asc())
        )
    ).all()
    return [
        {
            "id": item.id,
            "applicant_id": account.id,
            "nickname": profile.nickname if profile else account.display_name,
            "pubg_id": profile.pubg_id if profile else "",
            "rank": profile.rank if profile else "",
            "server": profile.server if profile else "",
            "has_mic": profile.has_mic if profile else False,
            "message": item.message,
            "created_at": item.created_at,
        }
        for item, account, profile in rows
    ]


# Static paths are intentionally declared before /{clan_id}.
@router.get("/mine")
async def mine(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    membership = await active_membership(db, user.id)
    if not membership:
        return None
    member, clan = membership
    payload = await clan_payload(db, clan, user)
    payload["members"] = await member_rows(db, clan.id)
    if member.role in {"owner", "officer"}:
        payload["applications"] = await application_rows(db, clan.id)
    else:
        payload["applications"] = []
    return payload


@router.get("/invites/mine")
async def my_invites(db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    rows = (
        await db.execute(
            select(ClanInvite, Clan, User)
            .join(Clan, Clan.id == ClanInvite.clan_id)
            .join(User, User.id == ClanInvite.invited_by)
            .where(ClanInvite.recipient_id == user.id)
            .order_by(ClanInvite.id.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": invite.id,
            "clan_id": clan.id,
            "clan_name": clan.name,
            "clan_tag": clan.tag,
            "clan_status": clan.status,
            "invited_by": inviter.display_name,
            "message": invite.message,
            "status": invite.status,
            "created_at": invite.created_at,
        }
        for invite, clan, inviter in rows
    ]


@router.post("/invites/{invite_id}/decision")
async def decide_invite(
    invite_id: int,
    payload: ClanInviteDecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    invite = await db.get(ClanInvite, invite_id)
    if not invite or invite.recipient_id != user.id:
        raise HTTPException(404, "Приглашение не найдено")
    if invite.status != "pending":
        return {"status": invite.status}
    clan = await require_clan(db, invite.clan_id)
    if payload.decision == "reject":
        invite.status = "rejected"
        invite.decided_at = datetime.utcnow()
        db.add(
            AuditLog(
                actor_id=user.id,
                action="clan.invite.reject",
                object_kind="clan",
                object_id=clan.id,
                details=log_details(invite_id=invite.id),
            )
        )
        await db.commit()
        return {"status": invite.status}

    current = await active_membership(db, user.id)
    if current and current[1].id != clan.id:
        raise HTTPException(409, f"Вы уже состоите в клане «{current[1].name}»")
    if await members_count(db, clan.id) >= clan.max_members:
        raise HTTPException(409, "В клане нет свободных мест")

    member = await accepted_member(db, clan.id, user.id)
    if not member:
        previous = (
            await db.execute(
                select(ClanMember).where(ClanMember.clan_id == clan.id, ClanMember.user_id == user.id)
            )
        ).scalar_one_or_none()
        if previous:
            previous.status = "accepted"
            previous.role = "member"
        else:
            db.add(ClanMember(clan_id=clan.id, user_id=user.id, role="member", status="accepted"))

    invite.status = "accepted"
    invite.decided_at = datetime.utcnow()
    await db.execute(
        update(ClanApplication)
        .where(ClanApplication.applicant_id == user.id, ClanApplication.status == "pending")
        .values(status="cancelled", decided_at=datetime.utcnow(), decision_note="Игрок вступил в другой клан")
    )
    await db.execute(
        update(ClanInvite)
        .where(ClanInvite.recipient_id == user.id, ClanInvite.status == "pending", ClanInvite.id != invite.id)
        .values(status="cancelled", decided_at=datetime.utcnow())
    )
    db.add(
        Notification(
            user_id=clan.owner_id,
            kind="clan_join",
            title="Игрок вступил в клан",
            text=f"Игрок принял приглашение в клан «{clan.name}».",
        )
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.invite.accept",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(invite_id=invite.id),
        )
    )
    await db.commit()
    return {"status": "accepted", "clan_id": clan.id}


@router.get("")
async def list_clans(
    q: str | None = Query(default=None, max_length=60),
    server: str | None = None,
    language: str | None = None,
    mode: str | None = None,
    map_name: str | None = None,
    min_rank: str | None = None,
    mic_required: bool | None = None,
    recruitment_open: bool | None = None,
    join_policy: str | None = Query(default=None, pattern="^(open|approval|invite_only)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    stmt = select(Clan).where(Clan.status == "active")
    if q:
        stmt = stmt.where(or_(Clan.name.ilike(f"%{q}%"), Clan.tag.ilike(f"%{q}%"), Clan.description.ilike(f"%{q}%")))
    if server:
        stmt = stmt.where(Clan.server == server)
    if language:
        stmt = stmt.where(Clan.language.ilike(f"%{language}%"))
    if mode:
        stmt = stmt.where(Clan.modes.ilike(f"%{mode}%"))
    if map_name:
        stmt = stmt.where(Clan.maps.ilike(f"%{map_name}%"))
    if min_rank:
        stmt = stmt.where(Clan.min_rank.ilike(f"%{min_rank}%"))
    if mic_required is not None:
        stmt = stmt.where(Clan.mic_required == mic_required)
    if recruitment_open is not None:
        stmt = stmt.where(Clan.recruitment_open == recruitment_open)
    if join_policy:
        stmt = stmt.where(Clan.join_policy == join_policy)
    rows = (await db.execute(stmt.order_by(Clan.id.desc()).limit(200))).scalars().all()
    payloads = [await clan_payload(db, clan, user) for clan in rows]
    payloads.sort(key=lambda item: (item["rating_score"], item["members_count"], item["id"]), reverse=True)
    for position, item in enumerate(payloads, start=1):
        item["rating_position"] = position
    return payloads[:100]


@router.post("")
async def create(payload: ClanIn, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    require_not_muted(user)
    current = await active_membership(db, user.id)
    if current:
        raise HTTPException(409, f"Сначала выйдите из клана «{current[1].name}»")

    duplicate = (
        await db.execute(
            select(Clan).where(
                Clan.status.in_(["active", "blocked"]),
                or_(func.lower(Clan.name) == payload.name.lower(), func.lower(Clan.tag) == payload.tag.lower()),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(409, "Клан с таким названием или тегом уже существует")

    if user.role not in {"owner", "admin"}:
        since = datetime.utcnow() - timedelta(hours=settings.clan_creation_cooldown_hours)
        recent = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.actor_id == user.id,
                    AuditLog.action == "clan.create",
                    AuditLog.created_at >= since,
                )
            )
        ).scalar_one_or_none()
        if recent:
            raise HTTPException(429, f"Новый клан можно создать через {settings.clan_creation_cooldown_hours} часов")

    clan = Clan(owner_id=user.id, **payload.model_dump())
    db.add(clan)
    await db.flush()
    db.add(ClanMember(clan_id=clan.id, user_id=user.id, role="owner", status="accepted"))
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.create",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(name=clan.name, tag=clan.tag),
        )
    )
    await db.commit()
    await db.refresh(clan)
    return await clan_payload(db, clan, user)


@router.get("/{clan_id}")
async def detail(clan_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    clan = await require_clan(db, clan_id)
    payload = await clan_payload(db, clan, user)
    payload["members"] = await member_rows(db, clan.id)
    member = await accepted_member(db, clan.id, user.id)
    payload["applications"] = await application_rows(db, clan.id) if member and member.role in {"owner", "officer"} else []
    return payload


@router.patch("/{clan_id}")
async def update_clan(
    clan_id: int,
    payload: ClanUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    clan, _ = await require_manager(db, clan_id, user, owner_only=True)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes or "tag" in changes:
        name = changes.get("name", clan.name)
        tag = changes.get("tag", clan.tag)
        duplicate = (
            await db.execute(
                select(Clan).where(
                    Clan.id != clan.id,
                    Clan.status.in_(["active", "blocked"]),
                    or_(func.lower(Clan.name) == name.lower(), func.lower(Clan.tag) == tag.lower()),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if duplicate:
            raise HTTPException(409, "Клан с таким названием или тегом уже существует")
    current_count = await members_count(db, clan.id)
    if changes.get("max_members", clan.max_members) < current_count:
        raise HTTPException(409, "Лимит не может быть меньше текущего состава")
    for key, value in changes.items():
        setattr(clan, key, value)
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.update",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(fields=sorted(changes)),
        )
    )
    await db.commit()
    return await clan_payload(db, clan, user)


@router.post("/{clan_id}/apply")
async def apply(
    clan_id: int,
    payload: ClanApplicationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_not_muted(user)
    clan = await require_clan(db, clan_id)
    if not clan.recruitment_open:
        raise HTTPException(409, "Набор в клан закрыт")
    if clan.join_policy == "invite_only":
        raise HTTPException(403, "В этот клан можно вступить только по приглашению")

    current = await active_membership(db, user.id)
    if current:
        if current[1].id == clan.id:
            return {"status": "accepted", "clan_id": clan.id}
        raise HTTPException(409, f"Вы уже состоите в клане «{current[1].name}»")
    if await members_count(db, clan.id) >= clan.max_members:
        raise HTTPException(409, "В клане нет свободных мест")

    pending = (
        await db.execute(
            select(ClanApplication).where(
                ClanApplication.clan_id == clan.id,
                ClanApplication.applicant_id == user.id,
                ClanApplication.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if pending:
        return {"status": "pending", "application_id": pending.id}

    application = ClanApplication(clan_id=clan.id, applicant_id=user.id, message=payload.message)
    if clan.join_policy == "open":
        application.status = "accepted"
        application.decided_by = user.id
        application.decided_at = datetime.utcnow()
        existing = (
            await db.execute(
                select(ClanMember).where(ClanMember.clan_id == clan.id, ClanMember.user_id == user.id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.status = "accepted"
            existing.role = "member"
        else:
            db.add(ClanMember(clan_id=clan.id, user_id=user.id, role="member", status="accepted"))
        action = "clan.join.open"
        notification_title = "Новый участник клана"
        notification_text = f"Игрок вступил в открытый клан «{clan.name}»."
    else:
        action = "clan.application.create"
        notification_title = "Заявка в клан"
        notification_text = f"Получена новая заявка в клан «{clan.name}»."

    db.add(application)
    db.add(Notification(user_id=clan.owner_id, kind="clan_request", title=notification_title, text=notification_text))
    db.add(
        AuditLog(
            actor_id=user.id,
            action=action,
            object_kind="clan",
            object_id=clan.id,
            details=log_details(application_id=None, message=payload.message[:120]),
        )
    )
    await db.commit()
    await db.refresh(application)
    return {"status": application.status, "application_id": application.id, "clan_id": clan.id}


@router.post("/{clan_id}/applications/{application_id}/decision")
async def decide_application(
    clan_id: int,
    application_id: int,
    payload: ClanDecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    clan, _ = await require_manager(db, clan_id, user)
    application = await db.get(ClanApplication, application_id)
    if not application or application.clan_id != clan.id:
        raise HTTPException(404, "Заявка не найдена")
    if application.status != "pending":
        return {"status": application.status}

    if payload.decision == "accept":
        current = await active_membership(db, application.applicant_id)
        if current and current[1].id != clan.id:
            raise HTTPException(409, "Игрок уже вступил в другой клан")
        if await members_count(db, clan.id) >= clan.max_members:
            raise HTTPException(409, "В клане нет свободных мест")
        member = (
            await db.execute(
                select(ClanMember).where(
                    ClanMember.clan_id == clan.id,
                    ClanMember.user_id == application.applicant_id,
                )
            )
        ).scalar_one_or_none()
        if member:
            member.status = "accepted"
            member.role = "member"
        else:
            db.add(
                ClanMember(
                    clan_id=clan.id,
                    user_id=application.applicant_id,
                    role="member",
                    status="accepted",
                )
            )
        application.status = "accepted"
        title = "Заявка принята"
        text_value = f"Вас приняли в клан «{clan.name}»."
        await db.execute(
            update(ClanApplication)
            .where(
                ClanApplication.applicant_id == application.applicant_id,
                ClanApplication.status == "pending",
                ClanApplication.id != application.id,
            )
            .values(status="cancelled", decided_at=datetime.utcnow(), decision_note="Игрок принят в другой клан")
        )
        await db.execute(
            update(ClanInvite)
            .where(ClanInvite.recipient_id == application.applicant_id, ClanInvite.status == "pending")
            .values(status="cancelled", decided_at=datetime.utcnow())
        )
    else:
        application.status = "rejected"
        title = "Заявка отклонена"
        text_value = f"Заявка в клан «{clan.name}» отклонена. {payload.note}".strip()

    application.decided_by = user.id
    application.decision_note = payload.note
    application.decided_at = datetime.utcnow()
    db.add(Notification(user_id=application.applicant_id, kind="clan_application", title=title, text=text_value))
    db.add(
        AuditLog(
            actor_id=user.id,
            action=f"clan.application.{application.status}",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(application_id=application.id, applicant_id=application.applicant_id, note=payload.note),
        )
    )
    await db.commit()
    return {"status": application.status}


@router.post("/{clan_id}/applications/{application_id}/cancel")
async def cancel_application(
    clan_id: int,
    application_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    application = await db.get(ClanApplication, application_id)
    if not application or application.clan_id != clan_id or application.applicant_id != user.id:
        raise HTTPException(404, "Заявка не найдена")
    if application.status == "pending":
        application.status = "cancelled"
        application.decided_at = datetime.utcnow()
        db.add(
            AuditLog(
                actor_id=user.id,
                action="clan.application.cancel",
                object_kind="clan",
                object_id=clan_id,
                details=log_details(application_id=application.id),
            )
        )
        await db.commit()
    return {"status": application.status}


@router.post("/{clan_id}/invites")
async def invite_player(
    clan_id: int,
    payload: ClanInviteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    require_not_muted(user)
    clan, _ = await require_manager(db, clan_id, user)
    if await members_count(db, clan.id) >= clan.max_members:
        raise HTTPException(409, "В клане нет свободных мест")

    term = payload.recipient.strip().lstrip("@").lower()
    conditions = [func.lower(User.username) == term, func.lower(User.display_name) == term]
    if term.isdigit():
        numeric = int(term)
        conditions.extend([User.id == numeric, User.telegram_id == numeric])
    target = (
        await db.execute(
            select(User)
            .outerjoin(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(
                or_(
                    *conditions,
                    func.lower(PlayerProfile.nickname) == term,
                    func.lower(PlayerProfile.pubg_id) == term,
                )
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Игрок не найден по ID, нику или @username")
    if target.id == user.id:
        raise HTTPException(400, "Нельзя пригласить себя")
    current = await active_membership(db, target.id)
    if current:
        raise HTTPException(409, f"Игрок уже состоит в клане «{current[1].name}»")
    pending = (
        await db.execute(
            select(ClanInvite).where(
                ClanInvite.clan_id == clan.id,
                ClanInvite.recipient_id == target.id,
                ClanInvite.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if pending:
        return {"id": pending.id, "status": pending.status}

    invite = ClanInvite(
        clan_id=clan.id,
        recipient_id=target.id,
        invited_by=user.id,
        message=payload.message,
    )
    db.add(invite)
    db.add(
        Notification(
            user_id=target.id,
            kind="clan_invite",
            title=f"Приглашение в клан [{clan.tag}]",
            text=payload.message or f"Вас приглашают в клан «{clan.name}».",
        )
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.invite.create",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(recipient_id=target.id),
        )
    )
    await db.commit()
    await db.refresh(invite)
    return {"id": invite.id, "status": invite.status, "recipient_id": target.id}


@router.post("/{clan_id}/members/{member_user_id}/role")
async def change_role(
    clan_id: int,
    member_user_id: int,
    payload: ClanRoleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    clan, _ = await require_manager(db, clan_id, user, owner_only=True)
    member = await accepted_member(db, clan.id, member_user_id)
    if not member:
        raise HTTPException(404, "Участник не найден")
    if member.role == "owner" or member.user_id == user.id:
        raise HTTPException(400, "Роль владельца меняется только передачей клана")
    member.role = payload.role
    db.add(
        Notification(
            user_id=member.user_id,
            kind="clan_role",
            title="Изменена роль в клане",
            text=f"Ваша роль в клане «{clan.name}»: {payload.role}.",
        )
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.member.role",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(user_id=member.user_id, role=payload.role),
        )
    )
    await db.commit()
    return {"role": member.role}


@router.delete("/{clan_id}/members/{member_user_id}")
async def remove_member(
    clan_id: int,
    member_user_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    clan, actor = await require_manager(db, clan_id, user)
    member = await accepted_member(db, clan.id, member_user_id)
    if not member:
        raise HTTPException(404, "Участник не найден")
    if member.role == "owner":
        raise HTTPException(400, "Владельца нельзя исключить")
    if actor.role == "officer" and member.role == "officer":
        raise HTTPException(403, "Офицер не может исключить другого офицера")
    member.status = "kicked"
    member.role = "member"
    db.add(
        Notification(
            user_id=member.user_id,
            kind="clan_kick",
            title="Исключение из клана",
            text=f"Вы исключены из клана «{clan.name}».",
        )
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.member.kick",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(user_id=member.user_id),
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/{clan_id}/leave")
async def leave(clan_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    clan = await require_clan(db, clan_id)
    member = await accepted_member(db, clan.id, user.id)
    if not member:
        raise HTTPException(404, "Вы не состоите в этом клане")
    if member.role == "owner":
        raise HTTPException(409, "Сначала передайте клан другому участнику или распустите его")
    member.status = "left"
    member.role = "member"
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.member.leave",
            object_kind="clan",
            object_id=clan.id,
            details="",
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/{clan_id}/recruitment")
async def set_recruitment(
    clan_id: int,
    payload: ClanRecruitmentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    clan, _ = await require_manager(db, clan_id, user)
    clan.recruitment_open = payload.recruitment_open
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.recruitment.open" if payload.recruitment_open else "clan.recruitment.close",
            object_kind="clan",
            object_id=clan.id,
            details="",
        )
    )
    await db.commit()
    return {"recruitment_open": clan.recruitment_open}


@router.post("/{clan_id}/transfer")
async def transfer(
    clan_id: int,
    payload: ClanTransferIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(auth_user),
):
    clan, owner_member = await require_manager(db, clan_id, user, owner_only=True)
    target = await accepted_member(db, clan.id, payload.user_id)
    if not target or target.user_id == user.id:
        raise HTTPException(404, "Новый владелец должен быть участником клана")
    owner_member.role = "officer"
    target.role = "owner"
    clan.owner_id = target.user_id
    db.add(
        Notification(
            user_id=target.user_id,
            kind="clan_owner",
            title="Вы стали владельцем клана",
            text=f"Вам передан клан «{clan.name}».",
        )
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.owner.transfer",
            object_kind="clan",
            object_id=clan.id,
            details=log_details(new_owner_id=target.user_id),
        )
    )
    await db.commit()
    return {"owner_id": clan.owner_id}


@router.post("/{clan_id}/disband")
async def disband(clan_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    clan, _ = await require_manager(db, clan_id, user, owner_only=True)
    clan.status = "closed"
    clan.recruitment_open = False
    await db.execute(
        update(ClanMember).where(ClanMember.clan_id == clan.id, ClanMember.status == "accepted").values(status="left")
    )
    await db.execute(
        update(ClanApplication)
        .where(ClanApplication.clan_id == clan.id, ClanApplication.status == "pending")
        .values(status="cancelled", decided_at=datetime.utcnow(), decision_note="Клан распущен")
    )
    await db.execute(
        update(ClanInvite)
        .where(ClanInvite.clan_id == clan.id, ClanInvite.status == "pending")
        .values(status="cancelled", decided_at=datetime.utcnow())
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            action="clan.disband",
            object_kind="clan",
            object_id=clan.id,
            details="",
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/{clan_id}/activity")
async def activity(clan_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(auth_user)):
    await require_manager(db, clan_id, user)
    rows = (
        await db.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .where(AuditLog.object_kind == "clan", AuditLog.object_id == clan_id)
            .order_by(AuditLog.id.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "actor_id": log.actor_id,
            "actor": actor.display_name if actor else "Система",
            "details": log.details,
            "created_at": log.created_at,
        }
        for log, actor in rows
    ]
