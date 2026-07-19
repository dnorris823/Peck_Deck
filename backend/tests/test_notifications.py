"""Tests for the per-recipient notification logic.

These exercise NotificationService directly (not through an HTTP route) with
send_email/send_sms monkeypatched, so we can assert exactly which recipients
were reached under each preference. Each test builds its own throwaway
user/device/species so shared-session state can't leak between tests.
"""
import asyncio
import secrets
from datetime import datetime, timezone

from backend.database.connection import get_session_factory
from backend.database.models import (
    Device,
    Sighting,
    Species,
    User,
    UserPreferences,
)
from backend.notifications import service as notif_module
from backend.notifications.service import NotificationService


async def _mk_user_device(*, notify_email=True, notify_sms=False, phone=None, prefs=None):
    async with get_session_factory()() as db:
        async with db.begin():
            email = f"notif_{secrets.token_hex(4)}@test.dev"
            u = User(
                name="Notif User", email=email, password_hash="x", phone=phone,
                role="owner", notify_email=notify_email, notify_sms=notify_sms,
            )
            db.add(u)
            await db.flush()
            d = Device(
                name="Notif Device", owner_id=u.id,
                classification_tier="auto", token=secrets.token_urlsafe(12),
            )
            db.add(d)
            await db.flush()
            if prefs is not None:
                db.add(UserPreferences(user_id=u.id, **prefs))
            return u.id, d.id, email


async def _mk_species() -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = Species(
                common_name=f"NotifBird {secrets.token_hex(3)}",
                genus="Genus", species_name="species",
            )
            db.add(sp)
            await db.flush()
            return sp.id


async def _insert_sighting(species_id: int, device_id: int) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            s = Sighting(
                species_id=species_id, device_id=device_id,
                datetime=datetime.now(timezone.utc), confidence_score=0.9,
                classification_tier_used="cloud", delayed=False,
            )
            db.add(s)
            await db.flush()
            return s.id


def _patch_senders(monkeypatch):
    emails: list[str] = []
    smses: list[str] = []

    async def fake_email(*, to_email, **_):
        emails.append(to_email)
        return True

    async def fake_sms(*, to_number, **_):
        smses.append(to_number)
        return True

    monkeypatch.setattr(notif_module, "send_email", fake_email)
    monkeypatch.setattr(notif_module, "send_sms", fake_sms)
    return emails, smses


def test_dispatch_reaches_email_and_sms_channels(client, monkeypatch):
    emails, smses = _patch_senders(monkeypatch)
    uid, did, email = asyncio.run(
        _mk_user_device(notify_email=True, notify_sms=True, phone="+15559999")
    )
    spid = asyncio.run(_mk_species())
    sid = asyncio.run(_insert_sighting(spid, did))

    asyncio.run(NotificationService().dispatch(sid, did))

    assert emails == [email]
    assert smses == ["+15559999"]


def test_new_species_only_notifies_first_but_skips_repeat(client, monkeypatch):
    emails, _ = _patch_senders(monkeypatch)
    uid, did, email = asyncio.run(
        _mk_user_device(prefs={"notify_new_species_only": True})
    )
    spid = asyncio.run(_mk_species())
    sid1 = asyncio.run(_insert_sighting(spid, did))  # count == 1

    # First sighting of the species → notified.
    asyncio.run(NotificationService().dispatch(sid1, did))
    assert emails == [email]

    # Second sighting of the same species → suppressed (count > 1).
    sid2 = asyncio.run(_insert_sighting(spid, did))  # count == 2
    asyncio.run(NotificationService().dispatch(sid2, did))
    assert emails == [email]  # unchanged


def test_per_recipient_throttle_suppresses_rapid_repeat(client, monkeypatch):
    emails, _ = _patch_senders(monkeypatch)
    uid, did, email = asyncio.run(_mk_user_device())
    spid = asyncio.run(_mk_species())
    sid = asyncio.run(_insert_sighting(spid, did))

    svc = NotificationService()  # shared instance keeps the throttle map
    asyncio.run(svc.dispatch(sid, did))
    asyncio.run(svc.dispatch(sid, did))  # within quiet interval → throttled

    assert emails == [email]


def test_throttle_is_independent_per_recipient(client, monkeypatch):
    """One recipient being throttled must not mute a different recipient."""
    emails, _ = _patch_senders(monkeypatch)
    # Two owners can't co-own one device, so model this as owner + member.
    async def _setup():
        async with get_session_factory()() as db:
            async with db.begin():
                from backend.database.models import DeviceUser
                a = User(name="A", email=f"a_{secrets.token_hex(4)}@t.dev",
                         password_hash="x", role="owner", notify_email=True)
                b = User(name="B", email=f"b_{secrets.token_hex(4)}@t.dev",
                         password_hash="x", role="viewer", notify_email=True)
                db.add_all([a, b])
                await db.flush()
                d = Device(name="Shared", owner_id=a.id,
                           classification_tier="auto", token=secrets.token_urlsafe(12))
                db.add(d)
                await db.flush()
                db.add(DeviceUser(device_id=d.id, user_id=b.id))
                return d.id, a.email, b.email

    did, a_email, b_email = asyncio.run(_setup())
    spid = asyncio.run(_mk_species())
    sid = asyncio.run(_insert_sighting(spid, did))

    asyncio.run(NotificationService().dispatch(sid, did))
    assert set(emails) == {a_email, b_email}


# ---------------------------------------------------------------------------
# Fire-and-forget failure isolation
# ---------------------------------------------------------------------------
def test_email_failure_does_not_block_sms(client, monkeypatch):
    """A raising email channel must not prevent the SMS channel from sending."""
    smses: list[str] = []

    async def boom_email(**_):
        raise RuntimeError("SendGrid exploded")

    async def fake_sms(*, to_number, **_):
        smses.append(to_number)
        return True

    monkeypatch.setattr(notif_module, "send_email", boom_email)
    monkeypatch.setattr(notif_module, "send_sms", fake_sms)

    uid, did, _ = asyncio.run(
        _mk_user_device(notify_email=True, notify_sms=True, phone="+15550000")
    )
    spid = asyncio.run(_mk_species())
    sid = asyncio.run(_insert_sighting(spid, did))

    # gather(return_exceptions=True) isolates the failure; SMS still lands.
    asyncio.run(NotificationService().dispatch(sid, did))
    assert smses == ["+15550000"]


def test_dispatch_swallows_send_failure(client, monkeypatch):
    """dispatch() is fire-and-forget: a channel error never propagates out."""
    async def boom_email(**_):
        raise RuntimeError("kaboom")

    async def fake_sms(**_):
        return True

    monkeypatch.setattr(notif_module, "send_email", boom_email)
    monkeypatch.setattr(notif_module, "send_sms", fake_sms)

    uid, did, _ = asyncio.run(_mk_user_device(notify_email=True))
    spid = asyncio.run(_mk_species())
    sid = asyncio.run(_insert_sighting(spid, did))

    # Must complete without raising.
    asyncio.run(NotificationService().dispatch(sid, did))


def test_dispatch_missing_sighting_is_noop(client, monkeypatch):
    """A dispatch for a non-existent sighting id returns cleanly (no send)."""
    emails, _ = _patch_senders(monkeypatch)
    uid, did, _ = asyncio.run(_mk_user_device())

    asyncio.run(NotificationService().dispatch(9_999_999, did))
    assert emails == []


def test_throttle_is_independent_per_device(client, monkeypatch):
    """One recipient throttled on device A can still be notified on device B."""
    emails, _ = _patch_senders(monkeypatch)

    async def _two_devices_one_owner():
        async with get_session_factory()() as db:
            async with db.begin():
                u = User(name="Multi", email=f"m_{secrets.token_hex(4)}@t.dev",
                         password_hash="x", role="owner", notify_email=True)
                db.add(u)
                await db.flush()
                d1 = Device(name="D1", owner_id=u.id, classification_tier="auto",
                            token=secrets.token_urlsafe(12))
                d2 = Device(name="D2", owner_id=u.id, classification_tier="auto",
                            token=secrets.token_urlsafe(12))
                db.add_all([d1, d2])
                await db.flush()
                return u.email, d1.id, d2.id

    email, d1, d2 = asyncio.run(_two_devices_one_owner())
    spid = asyncio.run(_mk_species())
    s1 = asyncio.run(_insert_sighting(spid, d1))
    s2 = asyncio.run(_insert_sighting(spid, d2))

    svc = NotificationService()  # one instance → shared throttle map
    asyncio.run(svc.dispatch(s1, d1))  # notified on device 1
    asyncio.run(svc.dispatch(s2, d2))  # different device → not throttled

    assert emails == [email, email]
