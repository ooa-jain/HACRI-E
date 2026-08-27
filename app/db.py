"""
MongoDB layer — unified for AI Survey + Orientation (Deeksharambh).

Collections:
  users                  — email PK, pre/post/orientation status
  pre_responses          — HACRI-E pre survey answers
  post_responses         — HACRI-E post survey answers
  orientation_responses  — Deeksharambh orientation answers (SEPARATE)
  feature_flags          — survey_enabled, orientation_enabled
"""
from __future__ import annotations
import time
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from pymongo import AsyncMongoClient, ReturnDocument
from app.settings import settings

log = logging.getLogger("hacri-e.db")

USERS = "users"
PRE   = "pre_responses"
POST  = "post_responses"
ORI   = "orientation_responses"
FLAGS = "feature_flags"
LOGINS = "admin_login_events"

# How many failures from one address, inside how long, before that address is
# turned away. Six is generous for a typing mistake and short of useful for
# anyone guessing.
LOGIN_FAIL_LIMIT = 6
LOGIN_FAIL_WINDOW_MINUTES = 15
LOGIN_LOCK_MINUTES = 15

STATUS_PRE_DONE  = "pre_done"
STATUS_POST_DONE = "post_done"
FLAG_SURVEY      = "survey_enabled"
FLAG_PRE_SURVEY  = "pre_survey_enabled"
FLAG_ORIENTATION = "orientation_enabled"
FLAG_POST_SURVEY = "post_survey_enabled"
FLAG_POST_DELAY  = "post_delay_days"
FLAG_TEST_MODE   = "test_mode_enabled"

# Label used wherever a student has no department recorded.
NO_DEPARTMENT    = "No Department"

_client = None
_db     = None


def get_client():
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    return _client


def get_db():
    global _db
    if _db is None:
        _db = get_client()[settings.mongodb_db]
    return _db


async def close_client():
    global _client, _db
    if _client:
        await _client.close()
        _client = None
        _db = None


def _set_client_for_tests(mock_client):
    global _client, _db
    _client = mock_client
    _db = mock_client[settings.mongodb_db]


def _reset_clients_for_tests():
    global _client, _db
    _client = None
    _db = None


async def _ensure_index(coll, keys, *, name, **opts):
    """Create an index, recovering from IndexOptionsConflict (85) or
    IndexKeySpecsConflict (86) by dropping any pre-existing index that
    covers the same key spec but has a different name. This keeps startup
    idempotent across schema revisions."""
    # Normalize the desired key spec the same way MongoDB does, so we can
    # compare against `list_indexes()` output: a bare field name is stored
    # as `{<field>: 1}`.
    if isinstance(keys, str):
        target_pairs = [(keys, 1)]
    elif isinstance(keys, list):
        target_pairs = [(k, 1) for (k, _) in keys]
    else:
        target_pairs = list(keys.items())

    try:
        await coll.create_index(keys, name=name, **opts)
        return
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code not in (85, 86):
            raise

    # Find the offending index and drop it, then recreate.
    async for ix in await coll.list_indexes():
        if ix.get("name") == name:
            continue
        key_dict = ix.get("key") or {}
        if list(key_dict.items()) != target_pairs:
            continue
        # Don't drop the _id_ index.
        if ix["name"] == "_id_":
            break
        await coll.drop_index(ix["name"])
        break

    await coll.create_index(keys, name=name, **opts)


async def init_indexes(allow_duplicate_email: bool = False):
    db = get_db()
    if allow_duplicate_email:
        await _ensure_index(db[USERS], "email", name="email_unique", unique=False)
    else:
        await _ensure_index(db[USERS], "email", name="email_unique", unique=True)
    # The admin dashboard lists users newest first, and filters by department
    # and level. Without these the sort is done in memory over the whole
    # collection on every load — slow while it works, and a hard failure once
    # the result passes MongoDB's 32MB in-memory sort limit.
    await _ensure_index(db[USERS], [("created_at", -1)], name="users_created_at")
    await _ensure_index(db[USERS], [("program", 1), ("ug_or_pg", 1)], name="users_program_level")
    await _ensure_index(db[PRE  ], "email", name="pre_email")
    await _ensure_index(db[POST ], "email", name="post_email")
    await _ensure_index(db[ORI  ], "email", name="ori_email")
    await _ensure_index(db[FLAGS], "key",   name="flags_key", unique=True)
    # The security page reads newest-first and counts recent failures per
    # address; both are unusable without these once the log has any age.
    await _ensure_index(db[LOGINS], [("at", -1)], name="logins_at")
    await _ensure_index(db[LOGINS], [("ip", 1), ("at", -1)], name="logins_ip_at")


# ── Admin sign-in log ─────────────────────────────────────────────────────────
#
# Every attempt on the admin portal, successful or not. The portal opens onto
# every student's contact details and every department's figures, and until now
# nothing recorded who had opened it or who had tried.
#
# What is stored is what the request itself carries: the address it came from,
# the browser string it announced, the username it offered. No password or OTP
# is ever written here — a log of failed attempts that contains the passwords
# people tried is a worse liability than no log at all.

# Outcomes, narrow on purpose so the page can colour them without guessing.
LOGIN_OK          = "success"        # signed in
LOGIN_BAD         = "bad_credentials"  # wrong username, password or OTP
LOGIN_OTP_SENT    = "otp_requested"  # a code was issued
LOGIN_UNKNOWN     = "unknown_user"   # no such admin username
LOGIN_LOCKED      = "locked_out"     # refused: too many recent failures
LOGIN_MAIL_OFF    = "otp_undelivered"  # code issued but mail is off or failed

FAILURE_OUTCOMES = (LOGIN_BAD, LOGIN_UNKNOWN, LOGIN_LOCKED)


async def record_login_event(
    *, username: str, outcome: str, ip: str = "", agent: str = "",
    portal: str = "", country: str = "", note: str = "",
) -> None:
    """Write one attempt to the log. Never raises — an audit trail that can
    take the login down with it is not worth having."""
    try:
        await get_db()[LOGINS].insert_one({
            "at": _now(),
            "username": (username or "")[:120],
            "outcome": outcome,
            "ip": (ip or "")[:64],
            "agent": (agent or "")[:400],
            "portal": portal,
            "country": country,
            "note": note[:200],
        })
    except Exception:  # pragma: no cover - logging must not break signing in
        log.exception("Could not record the admin login event")


async def list_login_events(limit: int = 200, outcome: str | None = None) -> list[dict]:
    """The log, newest first."""
    query: dict[str, Any] = {}
    if outcome:
        query["outcome"] = outcome
    rows = []
    async for doc in get_db()[LOGINS].find(query).sort("at", -1).limit(limit):
        doc.pop("_id", None)
        doc["at"] = _fmt(doc.get("at"))
        rows.append(doc)
    return rows


async def count_recent_failures(ip: str, minutes: int = LOGIN_FAIL_WINDOW_MINUTES) -> int:
    """Failed attempts from one address inside the window."""
    if not ip:
        return 0
    since = _now() - timedelta(minutes=minutes)
    return await get_db()[LOGINS].count_documents({
        "ip": ip, "at": {"$gte": since}, "outcome": {"$in": list(FAILURE_OUTCOMES)},
    })


async def is_locked_out(ip: str) -> bool:
    return await count_recent_failures(ip) >= LOGIN_FAIL_LIMIT


async def login_summary(hours: int = 24) -> dict:
    """What the security page puts at the top: the shape of the last day."""
    since = _now() - timedelta(hours=hours)
    coll = get_db()[LOGINS]

    signins = await coll.count_documents({"at": {"$gte": since}, "outcome": LOGIN_OK})
    failures = await coll.count_documents(
        {"at": {"$gte": since}, "outcome": {"$in": list(FAILURE_OUTCOMES)}})

    addresses: dict[str, dict] = {}
    async for doc in coll.find({"at": {"$gte": since}}):
        ip = doc.get("ip") or "unknown"
        row = addresses.setdefault(ip, {"ip": ip, "attempts": 0, "failures": 0,
                                        "usernames": set(), "last": None})
        row["attempts"] += 1
        if doc.get("outcome") in FAILURE_OUTCOMES:
            row["failures"] += 1
        if doc.get("username"):
            row["usernames"].add(doc["username"])
        when = doc.get("at")
        if row["last"] is None or (isinstance(when, datetime) and when > row["last"]):
            row["last"] = when

    offenders = []
    for row in addresses.values():
        if not row["failures"]:
            continue
        offenders.append({
            "ip": row["ip"],
            "attempts": row["attempts"],
            "failures": row["failures"],
            "usernames": sorted(row["usernames"])[:4],
            "last": _fmt(row["last"]),
            "locked": row["failures"] >= LOGIN_FAIL_LIMIT,
        })
    offenders.sort(key=lambda r: -r["failures"])

    return {
        "hours": hours,
        "signins": signins,
        "failures": failures,
        "addresses": len(addresses),
        "locked": sum(1 for o in offenders if o["locked"]),
        "offenders": offenders[:20],
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Feature flags ──────────────────────────────────────────────────────────────
async def get_flag(key: str, default: bool = True) -> bool:
    doc = await get_db()[FLAGS].find_one({"key": key})
    return bool(doc.get("enabled", default)) if doc else default


async def get_setting_int(key: str, default: int = 0) -> int:
    doc = await get_db()[FLAGS].find_one({"key": key})
    if doc and "value" in doc:
        try:
            return int(doc["value"])
        except (ValueError, TypeError):
            pass
    return default


async def set_flag(key: str, enabled: bool) -> None:
    await get_db()[FLAGS].update_one(
        {"key": key},
        {"$set": {"key": key, "enabled": enabled, "updated_at": _now()}},
        upsert=True,
    )


async def save_otp(key: str, otp: str) -> None:
    await get_db()[FLAGS].update_one(
        {"key": f"otp_{key}"},
        {"$set": {"value": otp, "updated_at": _now()}},
        upsert=True,
    )


async def verify_otp(key: str, otp: str) -> bool:
    doc = await get_db()[FLAGS].find_one({"key": f"otp_{key}"})
    if doc and doc.get("value") == otp:
        updated_at = doc.get("updated_at")
        if updated_at:
            delta = _now() - updated_at
            if delta.total_seconds() < 600:  # 10 minutes expiry
                return True
    return False


async def get_all_flags() -> dict[str, Any]:
    flags: dict[str, Any] = {}
    async for doc in get_db()[FLAGS].find():
        if doc["key"] in (
            "post_delay_days", "post_survey_delay_days",
            "auto_reminder_delay_days", "auto_reminder_first_delay_days",
            "auto_reminder_repeat_days"
        ):
            try:
                flags[doc["key"]] = int(doc.get("value", 0))
            except (ValueError, TypeError):
                flags[doc["key"]] = 0
        else:
            flags[doc["key"]] = bool(doc.get("enabled", True))
    flags.setdefault(FLAG_SURVEY,      True)
    flags.setdefault(FLAG_PRE_SURVEY,  True)
    flags.setdefault(FLAG_ORIENTATION, True)
    flags.setdefault(FLAG_POST_SURVEY, True)
    flags.setdefault(FLAG_POST_DELAY,  0)
    flags.setdefault(FLAG_TEST_MODE,   False)
    flags.setdefault("auto_reminders_enabled", False)
    flags.setdefault("auto_reminder_delay_days", 5)
    flags.setdefault("auto_reminder_repeat_days", 1)
    
    flags["post_survey_delay_days"] = flags.get("post_delay_days", flags.get("post_survey_delay_days", 0))
    flags["auto_reminder_first_delay_days"] = flags.get("auto_reminder_delay_days", flags.get("auto_reminder_first_delay_days", 5))
    return flags


# ── Users ──────────────────────────────────────────────────────────────────────
async def upsert_user(
    email: str,
    name: str,
    program: str = "",
    ug_or_pg: str | None = None,
    education_type: str | None = None,
    location: str | None = None,
) -> dict:
    now = _now()
    update: dict[str, Any] = {"name": name, "program": program.strip(), "updated_at": now}
    if ug_or_pg is not None:
        update["ug_or_pg"] = ug_or_pg
    if education_type is not None:
        update["education_type"] = education_type
    if location is not None:
        update["location"] = location
    return await get_db()[USERS].find_one_and_update(
        {"email": email},
        {
            "$set":       update,
            "$setOnInsert": {"email": email, "created_at": now, "status": None},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def email_filter(email: str) -> dict:
    """A Mongo filter matching one address however it happens to be cased.

    Registration stores an address exactly as it was typed, and the session
    cookie carries exactly what was typed at sign-in, so the two need not
    match. A student who registered as "Rahul.M@..." and signed in as
    "rahul.m@..." was, to an exact-match query, a different person: their
    record was not found, their orientation reply was filed against nobody,
    and the page after submit sent them back to the landing page.

    Use this anywhere a lookup or an update decides who a student is.
    """
    text = (email or "").strip()
    return {"email": {"$regex": f"^{re.escape(text)}$", "$options": "i"}}


async def get_user(email: str) -> dict | None:
    return await get_db()[USERS].find_one(email_filter(email))


# ── Pre survey ─────────────────────────────────────────────────────────────────
async def save_pre_response(email: str, name: str, fields: dict) -> tuple[str, dict]:
    """Save pre-survey response. Returns (pre_id, updated_user)."""
    db = get_db(); now = _now()
    res = await db[PRE].insert_one(
        {"email": email, "name": name, "submitted_at": now, "fields": fields}
    )
    pre_id = str(res.inserted_id)
    set_dict: dict[str, Any] = {
        "status": STATUS_PRE_DONE,
        "pre_id": pre_id,
        "pre_submitted_at": now,
        "updated_at": now,
        "education_type": fields.get("A4", "")
    }
    loc = fields.get("A7") or fields.get("location")
    if loc:
        set_dict["location"] = loc

    user = await db[USERS].find_one_and_update(
        {"email": email},
        {"$set": set_dict},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return pre_id, user


async def get_pre_fields(email: str) -> dict | None:
    doc = await get_db()[PRE].find_one({"email": email}, sort=[("submitted_at", -1)])
    return doc.get("fields") if doc else None


async def get_pre_name(email: str) -> str | None:
    """Return name stored in the pre-survey record (for orientation pre-fill)."""
    doc = await get_db()[PRE].find_one({"email": email}, sort=[("submitted_at", -1)])
    return doc.get("name") if doc else None


# ── Post survey ────────────────────────────────────────────────────────────────
async def save_post_response(email: str, name: str, fields: dict) -> tuple[str, dict]:
    """Save post-survey response. Returns (post_id, updated_user)."""
    db = get_db(); now = _now()
    res = await db[POST].insert_one(
        {"email": email, "name": name, "submitted_at": now, "fields": fields}
    )
    post_id = str(res.inserted_id)
    set_dict: dict[str, Any] = {
        "status": STATUS_POST_DONE,
        "post_id": post_id,
        "post_submitted_at": now,
        "updated_at": now
    }
    loc = fields.get("location")
    if loc:
        set_dict["location"] = loc

    user = await db[USERS].find_one_and_update(
        {"email": email},
        {"$set": set_dict},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return post_id, user


async def get_post_fields(email: str) -> dict | None:
    doc = await get_db()[POST].find_one({"email": email}, sort=[("submitted_at", -1)])
    return doc.get("fields") if doc else None


# ── Orientation (Deeksharambh) — completely separate ──────────────────────────
async def save_orientation_response(email: str, name: str, data: dict) -> str:
    """Store orientation form data. Returns doc id."""
    now = _now()
    clean_email = email.strip().lower()
    res = await get_db()[ORI].insert_one(
        {"email": clean_email, "name": name, "submitted_at": now, "data": data}
    )
    await get_db()[USERS].update_one(
        {"$or": [{"email": clean_email}, {"email": email}]},
        {"$set": {"orientation_submitted": True, "orientation_at": now, "updated_at": now}},
    )
    return str(res.inserted_id)


async def get_orientation_response(email: str) -> dict | None:
    return await get_db()[ORI].find_one({"email": email}, sort=[("submitted_at", -1)])


# ── Admin queries ──────────────────────────────────────────────────────────────
def _fmt(dt: Any) -> str:
    return dt.strftime("%d %b %Y %H:%M") if isinstance(dt, datetime) else ""


async def list_survey_users(limit: int = 10_000, dept: str | None = None, ug_or_pg: str | None = None) -> list[dict]:
    import base64
    query = {}
    if dept and dept.strip().lower() not in ("all departments", "all", "overall"):
        if dept in ("No Program", "No Department", "none", "None"):
            query["program"] = {"$in": ["", None, "No Program", "No Department"]}
        else:
            query["program"] = dept
    if ug_or_pg:
        query["ug_or_pg"] = ug_or_pg

    # Only the fields the dashboard actually reads. Fetching whole documents
    # made every row carry payload nothing rendered, over the wire and through
    # the sort.
    fields = {
        "email", "name", "program", "ug_or_pg", "location", "education_type",
        "status", "orientation_submitted", "created_at", "pre_submitted_at",
        "post_submitted_at", "orientation_at", "pre_reminder_sent_at",
        "post_reminder_sent_at", "pre_reminder_count", "post_reminder_count",
        "reminder_clicked_at", "last_email_error", "email_failed_at",
    }
    projection = {name: 1 for name in fields}

    result = []
    async for u in get_db()[USERS].find(query, projection).sort("created_at", -1).limit(limit):
        # A record with no email is not worth losing the whole dashboard over:
        # `u["email"]` raised KeyError and took every other student with it.
        email = u.get("email") or ""
        slug = base64.urlsafe_b64encode(email.lower().encode()).rstrip(b"=").decode()
        pre_reminder = u.get("pre_reminder_sent_at")
        post_reminder = u.get("post_reminder_sent_at")
        clicked = u.get("reminder_clicked_at")
        pre_sub = u.get("pre_submitted_at")
        post_sub = u.get("post_submitted_at")

        completed_after = False
        if clicked:
            if post_sub and post_sub > clicked:
                completed_after = True
            elif pre_sub and pre_sub > clicked:
                completed_after = True

        result.append({
            "email":                email,
            "email_slug":           slug,
            "name":                 u.get("name", ""),
            "program":              u.get("program", ""),
            "ug_or_pg":             u.get("ug_or_pg", "ug"),
            "location":              u.get("location", "Bangalore"),
            "education_type":      u.get("education_type", ""),
            "status":              u.get("status") or "not_started",
            "orientation_submitted": u.get("orientation_submitted", False),
            "created_at":          _fmt(u.get("created_at")),
            "created_at_iso":      u.get("created_at").isoformat() if isinstance(u.get("created_at"), datetime) else "",
            "pre_at":              _fmt(pre_sub),
            "pre_submitted_at_iso": pre_sub.isoformat() if isinstance(pre_sub, datetime) else "",
            "post_at":             _fmt(post_sub),
            "post_submitted_at_iso": post_sub.isoformat() if isinstance(post_sub, datetime) else "",
            "orientation_at":      _fmt(u.get("orientation_at")),
            "pre_reminder_at":     _fmt(pre_reminder) if isinstance(pre_reminder, datetime) else "",
            "post_reminder_at":    _fmt(post_reminder) if isinstance(post_reminder, datetime) else "",
            "pre_reminder_count":  int(u.get("pre_reminder_count", 0) or 0),
            "post_reminder_count": int(u.get("post_reminder_count", 0) or 0),
            "reminder_clicked_at": _fmt(clicked),
            "completed_after_reminder": completed_after,
            "last_email_error":    u.get("last_email_error", ""),
            "email_failed_at":     _fmt(u.get("email_failed_at")),
        })
    return result


async def list_orientation_responses(limit: int = 10_000) -> list[dict]:
    result = []
    async for doc in get_db()[ORI].find({}).sort("submitted_at", -1).limit(limit):
        email = doc.get("email", "")
        user = await get_db()[USERS].find_one({"email": email}) if email else None
        result.append({
            "email":        email,
            "name":         doc.get("name", ""),
            "submitted_at": _fmt(doc.get("submitted_at")),
            "ug_or_pg":    (user or {}).get("ug_or_pg", "ug") if user else "ug",
            "program":      (user or {}).get("program", "") if user else "",
            "data":         doc.get("data", {}),
        })
    return result


async def list_matched_users(
    program: str | None = None,
    ug_or_pg: str | None = None,
    limit: int = 10_000,
) -> dict[str, dict]:
    """Return {email: {pre: fields, post: fields}} for users with both surveys done."""
    db = get_db()
    query = {"status": STATUS_POST_DONE}
    if program and program.strip().lower() not in ("all departments", "all", "overall"):
        if program in ("No Program", "No Department", "none", "None"):
            query["program"] = {"$in": ["", None, "No Program", "No Department"]}
        else:
            query["program"] = program
    if ug_or_pg:
        query["ug_or_pg"] = ug_or_pg
    matched: dict[str, dict] = {}
    async for u in db[USERS].find(query).limit(limit):
        email = u["email"]
        pre  = await db[PRE ].find_one({"email": email}, sort=[("submitted_at", -1)])
        post = await db[POST].find_one({"email": email}, sort=[("submitted_at", -1)])
        if pre and post:
            matched[email] = {"pre": pre.get("fields", {}), "post": post.get("fields", {})}
    return matched


async def get_dept_analysis_data() -> dict[str, Any]:
    """
    Calculate department-wise registration, completion, and AI Literacy & Readiness scores.
    Uses AVERAGE (mean score) for department ranking/comparisons.
    """
    from app.scoring import score_for_user
    from app.routes.shared_analysis import get_dept_token
    db = get_db()

    email_to_dept: dict[str, str] = {}
    dept_user_counts: dict[str, dict[str, int]] = {}

    async for u in db[USERS].find({}):
        email = u.get("email")
        if not email:
            continue
        dept = u.get("program") or "Other"
        dept = dept.strip() or "Other"
        email_to_dept[email] = dept

        if dept not in dept_user_counts:
            dept_user_counts[dept] = {"registered": 0, "pre_done": 0, "post_done": 0}

        dept_user_counts[dept]["registered"] += 1
        st = u.get("status")
        if st in (STATUS_PRE_DONE, STATUS_POST_DONE):
            dept_user_counts[dept]["pre_done"] += 1
        if st == STATUS_POST_DONE:
            dept_user_counts[dept]["post_done"] += 1

    pre_scores_by_dept: dict[str, list[tuple[float, float]]] = {}
    post_scores_by_dept: dict[str, list[tuple[float, float]]] = {}

    async for doc in db[PRE].find({}):
        email = doc.get("email")
        dept = email_to_dept.get(email, "Other")
        fields = doc.get("fields", {})
        scores = score_for_user(fields)
        lit = scores.get("lit")
        read = scores.get("read")
        if lit is not None and read is not None:
            if dept not in pre_scores_by_dept:
                pre_scores_by_dept[dept] = []
            pre_scores_by_dept[dept].append((float(lit), float(read)))

    async for doc in db[POST].find({}):
        email = doc.get("email")
        dept = email_to_dept.get(email, "Other")
        fields = doc.get("fields", {})
        scores = score_for_user(fields)
        lit = scores.get("lit")
        read = scores.get("read")
        if lit is not None and read is not None:
            if dept not in post_scores_by_dept:
                post_scores_by_dept[dept] = []
            post_scores_by_dept[dept].append((float(lit), float(read)))

    all_depts = sorted(list(set(dept_user_counts.keys()) | set(pre_scores_by_dept.keys()) | set(post_scores_by_dept.keys())))

    dept_list = []
    overall_registered = sum(c["registered"] for c in dept_user_counts.values())
    overall_pre_done = sum(c["pre_done"] for c in dept_user_counts.values())
    overall_post_done = sum(c["post_done"] for c in dept_user_counts.values())

    all_pre_lit: list[float] = []
    all_pre_read: list[float] = []
    all_post_lit: list[float] = []
    all_post_read: list[float] = []

    base_url = str(settings.public_base_url).rstrip('/')

    for dept in all_depts:
        counts = dept_user_counts.get(dept, {"registered": 0, "pre_done": 0, "post_done": 0})
        reg = counts["registered"]
        pre_d = counts["pre_done"]
        post_d = counts["post_done"]

        pre_pairs = pre_scores_by_dept.get(dept, [])
        post_pairs = post_scores_by_dept.get(dept, [])

        avg_lit_pre = round(sum(p[0] for p in pre_pairs) / len(pre_pairs), 2) if pre_pairs else None
        avg_read_pre = round(sum(p[1] for p in pre_pairs) / len(pre_pairs), 2) if pre_pairs else None

        avg_lit_post = round(sum(p[0] for p in post_pairs) / len(post_pairs), 2) if post_pairs else None
        avg_read_post = round(sum(p[1] for p in post_pairs) / len(post_pairs), 2) if post_pairs else None

        if pre_pairs:
            all_pre_lit.extend([p[0] for p in pre_pairs])
            all_pre_read.extend([p[1] for p in pre_pairs])
        if post_pairs:
            all_post_lit.extend([p[0] for p in post_pairs])
            all_post_read.extend([p[1] for p in post_pairs])

        token_pre = get_dept_token(dept, "pre")
        token_post = get_dept_token(dept, "post")

        dept_list.append({
            "dept": dept,
            "registered": reg,
            "pre_done": pre_d,
            "post_done": post_d,
            "pre_pending": max(0, reg - pre_d),
            "post_pending": max(0, pre_d - post_d),
            "avg_lit_pre": avg_lit_pre,
            "avg_read_pre": avg_read_pre,
            "avg_lit_post": avg_lit_post,
            "avg_read_post": avg_read_post,
            "pre_count": len(pre_pairs),
            "post_count": len(post_pairs),
            "token_pre": token_pre,
            "token_post": token_post,
            "share_url_pre": f"{base_url}/shared/analysis?dept={dept}&token={token_pre}&type=pre",
            "share_url_post": f"{base_url}/shared/analysis?dept={dept}&token={token_post}&type=post",
        })

    overall_avg_lit_pre = round(sum(all_pre_lit) / len(all_pre_lit), 2) if all_pre_lit else None
    overall_avg_read_pre = round(sum(all_pre_read) / len(all_pre_read), 2) if all_pre_read else None
    overall_avg_lit_post = round(sum(all_post_lit) / len(all_post_lit), 2) if all_post_lit else None
    overall_avg_read_post = round(sum(all_post_read) / len(all_post_read), 2) if all_post_read else None

    token_overall_pre = get_dept_token("Overall", "pre")
    token_overall_post = get_dept_token("Overall", "post")

    overall_data = {
        "dept": "Overall",
        "registered": overall_registered,
        "pre_done": overall_pre_done,
        "post_done": overall_post_done,
        "pre_pending": max(0, overall_registered - overall_pre_done),
        "post_pending": max(0, overall_pre_done - overall_post_done),
        "avg_lit_pre": overall_avg_lit_pre,
        "avg_read_pre": overall_avg_read_pre,
        "avg_lit_post": overall_avg_lit_post,
        "avg_read_post": overall_avg_read_post,
        "pre_count": len(all_pre_lit),
        "post_count": len(all_post_lit),
        "token_pre": token_overall_pre,
        "token_post": token_overall_post,
        "share_url_pre": f"{base_url}/shared/analysis?dept=Overall&token={token_overall_pre}&type=pre",
        "share_url_post": f"{base_url}/shared/analysis?dept=Overall&token={token_overall_post}&type=post",
    }

    def find_rankings(key: str) -> dict[str, dict[str, Any] | None]:
        valid = [d for d in dept_list if d[key] is not None]
        if not valid:
            return {"highest": None, "lowest": None}
        sorted_depts = sorted(valid, key=lambda x: x[key], reverse=True)
        count_key = "post_count" if "post" in key else "pre_count"
        done_key = "post_done" if "post" in key else "pre_done"
        
        hi = sorted_depts[0]
        lo = sorted_depts[-1]

        return {
            "highest": {
                "dept": hi["dept"],
                "score": hi[key],
                "filled_count": hi.get(count_key, hi.get(done_key, 0)),
                "registered": hi.get("registered", 0),
            },
            "lowest": {
                "dept": lo["dept"],
                "score": lo[key],
                "filled_count": lo.get(count_key, lo.get(done_key, 0)),
                "registered": lo.get("registered", 0),
            }
        }

    rankings = {
        "lit_pre": find_rankings("avg_lit_pre"),
        "read_pre": find_rankings("avg_read_pre"),
        "lit_post": find_rankings("avg_lit_post"),
        "read_post": find_rankings("avg_read_post"),
    }

    return {
        "overall": overall_data,
        "departments": dept_list,
        "rankings": rankings
    }


async def get_dept_stats() -> list[dict]:
    """Return per-department stats: registered, pre_done, post_done counts + avg scores."""
    data = await get_dept_analysis_data()
    return data["departments"]


async def department_registration_summary() -> dict:
    """One row per department: registered, baseline, post survey, Deeksharambh.

    Built for the single-tab export the admin overview offers — every count on
    one row, drawn from the same student → department map, so the four
    columns can be read side by side without the department itself drifting
    between them. `get_dept_analysis_data()` computes registered/pre/post the
    same way but as three sheets; this adds the fourth figure (Deeksharambh)
    and flattens all four onto one row per department instead.

    A student counts once in `orientation_done` no matter how many times they
    resubmitted the form — distinct emails, not response rows.
    """
    db = get_db()

    email_to_dept: dict[str, str] = {}
    counts: dict[str, dict[str, int]] = {}

    def bucket(dept: str) -> dict:
        return counts.setdefault(dept, {
            "registered": 0, "pre_done": 0, "post_done": 0, "orientation_done": 0,
        })

    async for u in db[USERS].find({}, {"email": 1, "program": 1, "status": 1}):
        email = (u.get("email") or "").strip().lower()
        if not email:
            continue
        dept = (u.get("program") or "").strip() or "Other"
        email_to_dept[email] = dept
        row = bucket(dept)
        row["registered"] += 1
        status = u.get("status")
        if status in (STATUS_PRE_DONE, STATUS_POST_DONE):
            row["pre_done"] += 1
        if status == STATUS_POST_DONE:
            row["post_done"] += 1

    seen_ori: set[str] = set()
    async for doc in db[ORI].find({}, {"email": 1}):
        email = (doc.get("email") or "").strip().lower()
        if not email or email in seen_ori:
            continue
        seen_ori.add(email)
        # A reply from a student we have no registration record for still
        # counts — filed under "Other" rather than dropped, the same rule the
        # rest of this file uses for an unmatched program.
        bucket(email_to_dept.get(email, "Other"))["orientation_done"] += 1

    rows = []
    for dept, c in counts.items():
        reg = c["registered"]
        rows.append({
            "dept": dept,
            "registered": reg,
            "pre_done": c["pre_done"],
            "pre_pending": max(0, reg - c["pre_done"]),
            "post_done": c["post_done"],
            "post_pending": max(0, c["pre_done"] - c["post_done"]),
            "orientation_done": c["orientation_done"],
            "orientation_pending": max(0, reg - c["orientation_done"]),
        })
    rows.sort(key=lambda r: (-r["registered"], r["dept"].lower()))

    totals = {
        key: sum(r[key] for r in rows)
        for key in ("registered", "pre_done", "pre_pending", "post_done",
                    "post_pending", "orientation_done", "orientation_pending")
    }
    return {"departments": rows, "totals": totals}


async def department_full_report() -> dict:
    """Everything the "whole report in one Excel" export needs: the same
    per-department totals as `department_registration_summary()`, plus every
    student behind those totals, grouped by department and ordered the same
    descending-by-registered way — so a reader opens the cohort tab, sees
    which department to look at first, and finds it in the same position
    among the per-department tabs.

    Whether a student counts as done for Pre/Post is read off `users.status`
    — the same field `department_registration_summary()` uses — so a
    student's row here always agrees with their contribution to the summary
    counts. The response collections only supply the *date* they submitted,
    since `status` alone doesn't carry a timestamp.
    """
    db = get_db()

    users_by_email: dict[str, dict] = {}
    async for u in db[USERS].find({}):
        email = (u.get("email") or "").strip().lower()
        if email:
            users_by_email[email] = u

    async def _first_submission(collection: str) -> dict[str, datetime]:
        """Earliest `submitted_at` per email — when a student first did it,
        not their latest resubmission."""
        at: dict[str, datetime] = {}
        async for doc in db[collection].find({}, {"email": 1, "submitted_at": 1}):
            email = (doc.get("email") or "").strip().lower()
            when = doc.get("submitted_at")
            if email and (email not in at or (
                    isinstance(when, datetime) and isinstance(at[email], datetime)
                    and when < at[email])):
                at[email] = when
        return at

    pre_at = await _first_submission(PRE)
    post_at = await _first_submission(POST)
    ori_at = await _first_submission(ORI)

    by_dept: dict[str, list[dict]] = {}
    for email, u in users_by_email.items():
        dept = (u.get("program") or "").strip() or "Other"
        status = u.get("status")
        pre_done = status in (STATUS_PRE_DONE, STATUS_POST_DONE)
        post_done = status == STATUS_POST_DONE
        by_dept.setdefault(dept, []).append({
            "name": u.get("name") or "",
            "email": u.get("email") or email,
            "level": (u.get("ug_or_pg") or "ug").upper(),
            "registered_at": u.get("created_at"),
            "pre_done": pre_done, "pre_at": pre_at.get(email),
            "post_done": post_done, "post_at": post_at.get(email),
            "orientation_done": email in ori_at, "orientation_at": ori_at.get(email),
        })

    # A Deeksharambh reply from an email with no registration record at all —
    # counted under "Other" in the summary, so it belongs on that tab too.
    for email, when in ori_at.items():
        if email in users_by_email:
            continue
        by_dept.setdefault("Other", []).append({
            "name": "", "email": email, "level": "—", "registered_at": None,
            "pre_done": False, "pre_at": None, "post_done": False, "post_at": None,
            "orientation_done": True, "orientation_at": when,
        })

    summary = await department_registration_summary()
    # Already sorted descending by registered — the same order every tab in
    # the workbook uses, so "top of the summary" and "first department tab"
    # always mean the same department.
    order = [r["dept"] for r in summary["departments"]]

    departments = []
    for dept in order:
        students = sorted(by_dept.get(dept, []),
                          key=lambda r: (r["name"] or r["email"]).lower())
        departments.append({"dept": dept, "students": students})

    return {"summary": summary, "departments": departments}



async def get_dept_students(dept: str) -> list[dict]:
    """Return all students for a given department with their pre/post status."""
    db = get_db()
    query = {"program": dept} if dept else {}
    result = []
    async for u in db[USERS].find(query).sort("created_at", -1):
        result.append({
            "email":      u["email"],
            "name":       u.get("name", ""),
            "program":    u.get("program", ""),
            "ug_or_pg":  u.get("ug_or_pg", "ug"),
            "status":     u.get("status") or "not_started",
            "pre_at":     _fmt(u.get("pre_submitted_at")),
            "post_at":    _fmt(u.get("post_submitted_at")),
        })
    return result


async def get_student_detail(email: str) -> dict | None:
    """Return full pre + post survey fields for one student."""
    db = get_db()
    user = await db[USERS].find_one({"email": email})
    if not user:
        return None
    pre_doc  = await db[PRE ].find_one({"email": email}, sort=[("submitted_at", -1)])
    post_doc = await db[POST].find_one({"email": email}, sort=[("submitted_at", -1)])
    return {
        "email":      email,
        "name":       user.get("name", ""),
        "program":    user.get("program", ""),
        "ug_or_pg":  user.get("ug_or_pg", "ug"),
        "status":     user.get("status") or "not_started",
        "pre_at":     _fmt(user.get("pre_submitted_at")),
        "post_at":    _fmt(user.get("post_submitted_at")),
        "pre_fields":  pre_doc.get("fields",  {}) if pre_doc  else {},
        "post_fields": post_doc.get("fields", {}) if post_doc else {},
    }


async def get_department_summary() -> list[dict]:
    """Per-department registration / completion counts.

    Used by the admin "department post links" panel so each generated link can
    show how many students it is actually meant to serve.
    """
    counts: dict[str, dict] = {}
    async for u in get_db()[USERS].find({}):
        dept = (u.get("program") or "").strip() or NO_DEPARTMENT
        entry = counts.setdefault(
            dept, {"dept": dept, "registered": 0, "pre_done": 0, "post_done": 0}
        )
        entry["registered"] += 1
        st = u.get("status")
        if st in (STATUS_PRE_DONE, STATUS_POST_DONE):
            entry["pre_done"] += 1
        if st == STATUS_POST_DONE:
            entry["post_done"] += 1

    for entry in counts.values():
        entry["pending_pre"] = entry["registered"] - entry["pre_done"]
        entry["pending_post"] = entry["pre_done"] - entry["post_done"]
    return sorted(counts.values(), key=lambda d: d["dept"].lower())


async def list_departments() -> list[str]:
    """Every distinct department name currently present on a user record."""
    seen: set[str] = set()
    async for u in get_db()[USERS].find({}):
        dept = (u.get("program") or "").strip()
        if dept:
            seen.add(dept)
    return sorted(seen, key=str.lower)


async def delete_user_and_responses(email: str) -> None:
    db = get_db()
    await db[USERS].delete_one({"email": email})
    await db[PRE].delete_many({"email": email})
    await db[POST].delete_many({"email": email})
    await db[ORI].delete_many({"email": email})


async def get_email_notification_stats() -> list[dict]:
    db = get_db()
    results = {}
    
    async for u in db[USERS].find({}):
        dept = u.get("program") or "No Program"
        if dept not in results:
            results[dept] = {
                "dept": dept,
                "pre_sent": 0,
                "post_sent": 0,
                "clicked": 0,
                "completed_after": 0,
                "in_draft": 0,
                "total_users": 0
            }
        
        entry = results[dept]
        entry["total_users"] += 1
        
        pre_reminder = u.get("pre_reminder_sent_at")
        post_reminder = u.get("post_reminder_sent_at")
        clicked = u.get("reminder_clicked_at")
        pre_sub = u.get("pre_submitted_at")
        post_sub = u.get("post_submitted_at")
        
        if pre_reminder:
            entry["pre_sent"] += 1
        if post_reminder:
            entry["post_sent"] += 1
        if clicked:
            entry["clicked"] += 1
            
        completed_after = False
        if clicked:
            if post_sub and post_sub > clicked:
                completed_after = True
            elif pre_sub and pre_sub > clicked:
                completed_after = True
                
        if completed_after:
            entry["completed_after"] += 1
            
        has_pre_draft = bool(u.get("pre_draft"))
        has_post_draft = bool(u.get("post_draft"))
        if has_pre_draft or has_post_draft:
            entry["in_draft"] += 1
            
    return sorted(results.values(), key=lambda x: x["dept"])


async def save_admin_otp(username: str, otp: str, expires_at: float):
    db = get_db()
    await db["admin_otps"].update_one(
        {"username": username},
        {"$set": {"otp": otp, "expires_at": expires_at}},
        upsert=True
    )


async def verify_admin_otp(username: str, otp: str) -> bool:
    db = get_db()
    doc = await db["admin_otps"].find_one({"username": username})
    if not doc:
        return False
    
    stored_otp = doc.get("otp")
    expires_at = doc.get("expires_at", 0)
    
    if otp == stored_otp and time.time() < expires_at:
        await db["admin_otps"].delete_one({"username": username})
        return True
    return False


async def get_date_analysis_data() -> dict[str, Any]:
    """
    Calculate calendar and date-wise survey response metrics per department and overall.
    Tracks start date, today's filling count, peak (Max) day, and lowest (Min) day per department,
    plus full date-by-date department breakdowns and student submission logs.
    """
    db = get_db()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Map email to program (department) and name
    email_to_user: dict[str, dict[str, str]] = {}
    async for u in db[USERS].find({}):
        email = u.get("email")
        if email:
            dept = u.get("program") or "Other"
            name = u.get("name") or "Student"
            email_to_user[email] = {
                "dept": dept.strip() or "Other",
                "name": name
            }

    dept_daily: dict[str, dict[str, dict[str, int]]] = {}
    overall_daily: dict[str, dict[str, int]] = {}
    by_date: dict[str, dict[str, Any]] = {}

    def add_entry(dept_name: str, dt: Any, survey_kind: str, email: str):
        if not isinstance(dt, datetime):
            return
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        # Department daily
        if dept_name not in dept_daily:
            dept_daily[dept_name] = {}
        if date_str not in dept_daily[dept_name]:
            dept_daily[dept_name][date_str] = {"pre": 0, "post": 0, "total": 0}
        dept_daily[dept_name][date_str][survey_kind] += 1
        dept_daily[dept_name][date_str]["total"] += 1

        # Overall daily
        if date_str not in overall_daily:
            overall_daily[date_str] = {"pre": 0, "post": 0, "total": 0}
        overall_daily[date_str][survey_kind] += 1
        overall_daily[date_str]["total"] += 1

        # Date detail breakdown
        if date_str not in by_date:
            by_date[date_str] = {
                "date": date_str,
                "pre": 0,
                "post": 0,
                "total": 0,
                "dept_counts": {},
                "students": []
            }
        d_info = by_date[date_str]
        d_info[survey_kind] += 1
        d_info["total"] += 1

        if dept_name not in d_info["dept_counts"]:
            d_info["dept_counts"][dept_name] = {"pre": 0, "post": 0, "total": 0}
        d_info["dept_counts"][dept_name][survey_kind] += 1
        d_info["dept_counts"][dept_name]["total"] += 1

        user_info = email_to_user.get(email, {"name": "Student", "dept": dept_name})
        d_info["students"].append({
            "name": user_info.get("name", "Student"),
            "email": email,
            "dept": dept_name,
            "type": survey_kind,
            "time": time_str
        })

    async for doc in db[PRE].find({}):
        email = doc.get("email", "")
        dept_name = email_to_user.get(email, {}).get("dept", "Other")
        sub_at = doc.get("submitted_at")
        add_entry(dept_name, sub_at, "pre", email)

    async for doc in db[POST].find({}):
        email = doc.get("email", "")
        dept_name = email_to_user.get(email, {}).get("dept", "Other")
        sub_at = doc.get("submitted_at")
        add_entry(dept_name, sub_at, "post", email)

    def compute_calendar_stats(daily_dict: dict[str, dict[str, int]], d_name: str):
        if not daily_dict:
            return {
                "dept": d_name,
                "start_date": "Not Started",
                "latest_date": "No Data",
                "active_days": 0,
                "today_pre": 0,
                "today_post": 0,
                "today_total": 0,
                "total_responses": 0,
                "max_day": None,
                "min_day": None,
                "daily_timeline": [],
            }

        sorted_dates = sorted(daily_dict.keys())
        start_date = sorted_dates[0]
        latest_date = sorted_dates[-1]
        active_days = len(sorted_dates)
        total_responses = sum(daily_dict[d]["total"] for d in sorted_dates)

        today_info = daily_dict.get(today_str, {"pre": 0, "post": 0, "total": 0})

        max_date = max(sorted_dates, key=lambda d: (daily_dict[d]["total"], d))
        max_day_info = {
            "date": max_date,
            "total": daily_dict[max_date]["total"],
            "pre": daily_dict[max_date]["pre"],
            "post": daily_dict[max_date]["post"],
        }

        min_date = min(sorted_dates, key=lambda d: (daily_dict[d]["total"], d))
        min_day_info = {
            "date": min_date,
            "total": daily_dict[min_date]["total"],
            "pre": daily_dict[min_date]["pre"],
            "post": daily_dict[min_date]["post"],
        }

        timeline = []
        for d_str in sorted_dates:
            timeline.append({
                "date": d_str,
                "pre": daily_dict[d_str]["pre"],
                "post": daily_dict[d_str]["post"],
                "total": daily_dict[d_str]["total"],
            })

        return {
            "dept": d_name,
            "start_date": start_date,
            "latest_date": latest_date,
            "active_days": active_days,
            "today_pre": today_info["pre"],
            "today_post": today_info["post"],
            "today_total": today_info["total"],
            "total_responses": total_responses,
            "max_day": max_day_info,
            "min_day": min_day_info,
            "daily_timeline": timeline,
        }

    overall_stats = compute_calendar_stats(overall_daily, "Overall")

    dept_summaries = []
    for dept_name in sorted(dept_daily.keys()):
        dept_summaries.append(compute_calendar_stats(dept_daily[dept_name], dept_name))

    highest_single_day_dept = None
    lowest_single_day_dept = None
    first_started_dept = None

    if dept_summaries:
        valid_summaries = [d for d in dept_summaries if d["max_day"] is not None]
        if valid_summaries:
            sorted_by_max = sorted(valid_summaries, key=lambda x: x["max_day"]["total"], reverse=True)
            highest_single_day_dept = {
                "dept": sorted_by_max[0]["dept"],
                "date": sorted_by_max[0]["max_day"]["date"],
                "count": sorted_by_max[0]["max_day"]["total"],
            }
            lowest_single_day_dept = {
                "dept": sorted_by_max[-1]["dept"],
                "date": sorted_by_max[-1]["min_day"]["date"],
                "count": sorted_by_max[-1]["min_day"]["total"],
            }
            sorted_by_start = sorted(valid_summaries, key=lambda x: x["start_date"])
            first_started_dept = {
                "dept": sorted_by_start[0]["dept"],
                "start_date": sorted_by_start[0]["start_date"],
            }

    all_dates = sorted(list(overall_daily.keys()))

    # Build formatted by_date output
    formatted_by_date: dict[str, dict[str, Any]] = {}
    for d_str, d_info in by_date.items():
        dept_list_for_date = []
        for d_name, d_c in d_info["dept_counts"].items():
            dept_list_for_date.append({
                "dept": d_name,
                "pre": d_c["pre"],
                "post": d_c["post"],
                "total": d_c["total"]
            })
        dept_list_for_date.sort(key=lambda x: x["total"], reverse=True)
        formatted_by_date[d_str] = {
            "date": d_str,
            "pre": d_info["pre"],
            "post": d_info["post"],
            "total": d_info["total"],
            "dept_breakdown": dept_list_for_date,
            "students": d_info["students"]
        }

    return {
        "overall": overall_stats,
        "departments": dept_summaries,
        "all_dates": all_dates,
        "today_date": today_str,
        "by_date": formatted_by_date,
        "highlights": {
            "highest_single_day": highest_single_day_dept,
            "lowest_single_day": lowest_single_day_dept,
            "first_started_dept": first_started_dept,
        }
    }

