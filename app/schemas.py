from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProfileIn(BaseModel):
    nickname: str = Field(min_length=2, max_length=40)
    pubg_id: str = Field(min_length=3, max_length=40)
    server: str = Field(max_length=40)
    language: str = Field(max_length=40, default="Русский")
    rank: str = Field(max_length=40, default="")
    role: str = Field(max_length=40, default="Универсал")
    modes: str = Field(max_length=200, default="Классика")
    maps: str = Field(max_length=200, default="")
    play_time: str = Field(max_length=80, default="")
    timezone: str = Field(max_length=64, default="UTC")
    has_mic: bool = False
    play_style: str = Field(max_length=80, default="")
    goal: str = Field(max_length=80, default="Тимейты")
    about: str = Field(max_length=1000, default="")
    is_visible: bool = True
    looking_for_team: bool = True


class RoomIn(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    server: str = Field(max_length=40)
    mode: str = Field(max_length=40)
    map_name: str = Field(max_length=40, default="")
    rank: str = Field(max_length=40, default="")
    language: str = Field(max_length=40, default="Русский")
    slots_total: int = Field(ge=2, le=4, default=4)
    mic_required: bool = False
    starts_at: str = Field(max_length=80, default="")
    note: str = Field(max_length=1000, default="")


class ClanIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    tag: str = Field(min_length=2, max_length=12)
    server: str = Field(max_length=40)
    language: str = Field(max_length=40, default="Русский")
    modes: str = Field(max_length=240, default="Классика")
    maps: str = Field(max_length=240, default="")
    min_rank: str = Field(max_length=40, default="")
    mic_required: bool = False
    requirements: str = Field(max_length=1000, default="")
    description: str = Field(max_length=1500, default="")
    contact: str = Field(max_length=120, default="")
    logo_url: str = Field(max_length=300, default="")
    max_members: int = Field(ge=2, le=100, default=30)
    join_policy: str = Field(pattern="^(open|approval|invite_only)$", default="approval")
    recruitment_open: bool = True

    @field_validator("name", "tag", "server", "language", "modes", "maps", "min_rank", "contact", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("tag")
    @classmethod
    def normalize_tag(cls, value: str) -> str:
        return value.upper().replace(" ", "")


class ClanUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    tag: str | None = Field(default=None, min_length=2, max_length=12)
    server: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=40)
    modes: str | None = Field(default=None, max_length=240)
    maps: str | None = Field(default=None, max_length=240)
    min_rank: str | None = Field(default=None, max_length=40)
    mic_required: bool | None = None
    requirements: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=1500)
    contact: str | None = Field(default=None, max_length=120)
    logo_url: str | None = Field(default=None, max_length=300)
    max_members: int | None = Field(default=None, ge=2, le=100)
    join_policy: str | None = Field(default=None, pattern="^(open|approval|invite_only)$")

    @field_validator("tag")
    @classmethod
    def normalize_tag(cls, value: str | None) -> str | None:
        return value.upper().replace(" ", "") if value else value


class ClanApplicationIn(BaseModel):
    message: str = Field(max_length=500, default="")


class ClanDecisionIn(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
    note: str = Field(max_length=500, default="")


class ClanInviteIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=80)
    message: str = Field(max_length=500, default="")


class ClanInviteDecisionIn(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")


class ClanRoleIn(BaseModel):
    role: str = Field(pattern="^(officer|member)$")


class ClanRecruitmentIn(BaseModel):
    recruitment_open: bool


class ClanTransferIn(BaseModel):
    user_id: int


class ClanModerationIn(BaseModel):
    decision: str = Field(pattern="^(block|unblock|close)$")
    reason: str = Field(max_length=1000, default="")


class InvitationIn(BaseModel):
    recipient_id: int
    kind: str = Field(pattern="^(teammate|room|clan)$")
    target_id: int | None = None
    message: str = Field(max_length=500, default="")


class ReportIn(BaseModel):
    target_kind: str = Field(pattern="^(user|profile|room|clan|ad)$")
    target_id: int
    category: str = Field(max_length=40)
    text: str = Field(min_length=3, max_length=1000)


class AdIn(BaseModel):
    tariff_id: int = Field(ge=1)
    category: str = Field(max_length=40)
    title: str = Field(min_length=3, max_length=80)
    text: str = Field(min_length=10, max_length=1500)
    url: str = Field(min_length=8, max_length=200)


class AdTariffIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(max_length=1000, default="")
    price_stars: int = Field(ge=1, le=100000)
    duration_days: int = Field(ge=1, le=365)
    placement: str = Field(pattern="^(standard|premium|top)$", default="standard")
    priority: int = Field(ge=0, le=10000, default=0)
    is_pinned: bool = False
    is_active: bool = True


class RefundIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class ModerateIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|close|ban|unban)$")
    reason: str = Field(max_length=1000, default="")


class OwnerUserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    username: str | None = Field(default=None, max_length=64)
    moderation_note: str | None = Field(default=None, max_length=2000)
    nickname: str | None = Field(default=None, min_length=2, max_length=40)
    pubg_id: str | None = Field(default=None, min_length=3, max_length=40)
    server: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=40)
    rank: str | None = Field(default=None, max_length=40)
    player_role: str | None = Field(default=None, max_length=40)
    modes: str | None = Field(default=None, max_length=200)
    maps: str | None = Field(default=None, max_length=200)
    play_time: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)
    has_mic: bool | None = None
    play_style: str | None = Field(default=None, max_length=80)
    goal: str | None = Field(default=None, max_length=80)
    about: str | None = Field(default=None, max_length=1000)
    is_visible: bool | None = None
    looking_for_team: bool | None = None


class OwnerUserActionIn(BaseModel):
    action: str = Field(pattern="^(ban|unban|mute|unmute|block_ads|unblock_ads|set_role)$")
    reason: str = Field(max_length=1000, default="")
    duration_hours: int | None = Field(default=None, ge=1, le=8760)
    role: str | None = Field(default=None, pattern="^(user|moderator|admin)$")


class RoomModerationIn(BaseModel):
    decision: str = Field(pattern="^(close|reopen|block)$")
    reason: str = Field(max_length=1000, default="")


class BroadcastIn(BaseModel):
    target: str = Field(pattern="^(all|users|clan_owners|room_owners|staff|active_7d|active_30d)$")
    title: str = Field(min_length=3, max_length=120)
    text: str = Field(min_length=3, max_length=3000)
