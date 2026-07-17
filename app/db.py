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
from datetime import datetime, timezone
from typing import Any
from pymongo import AsyncMongoClient, ReturnDocument
from app.settings import settings

USERS = "users"
PRE   = "pre_responses"
POST  = "post_responses"
ORI   = "orientation_responses"
FLAGS = "feature_flags"

STATUS_PRE_DONE  = "pre_done"
STATUS_POST_DONE = "post_done"
FLAG_SURVEY      = "survey_enabled"
FLAG_PRE_SURVEY  = "pre_survey_enabled"
FLAG_ORIENTATION = "orientation_enabled"
FLAG_POST_SURVEY = "post_survey_enabled"
FLAG_POST_DELAY  = "post_delay_days"
FLAG_TEST_MODE   = "test_mode_enabled"

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
    await _ensure_index(db[PRE  ], "email", name="pre_email")
    await _ensure_index(db[POST ], "email", name="post_email")
    await _ensure_index(db[ORI  ], "email", name="ori_email")
    await _ensure_index(db[FLAGS], "key",   name="flags_key", unique=True)


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
        if doc["key"] == "post_delay_days":
            flags[doc["key"]] = int(doc.get("value", 0))
        else:
            flags[doc["key"]] = bool(doc.get("enabled", True))
    flags.setdefault(FLAG_SURVEY,      True)
    flags.setdefault(FLAG_PRE_SURVEY,  True)
    flags.setdefault(FLAG_ORIENTATION, False)
    flags.setdefault(FLAG_POST_SURVEY, True)
    flags.setdefault(FLAG_POST_DELAY,  0)
    flags.setdefault(FLAG_TEST_MODE,   False)
    return flags


# ── Users ──────────────────────────────────────────────────────────────────────
async def upsert_user(
    email: str,
    name: str,
    program: str = "",
    ug_or_pg: str | None = None,
    education_type: str | None = None,
) -> dict:
    now = _now()
    update: dict[str, Any] = {"name": name, "program": program.strip(), "updated_at": now}
    if ug_or_pg is not None:
        update["ug_or_pg"] = ug_or_pg
    if education_type is not None:
        update["education_type"] = education_type
    return await get_db()[USERS].find_one_and_update(
        {"email": email},
        {
            "$set":       update,
            "$setOnInsert": {"email": email, "created_at": now, "status": None},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def get_user(email: str) -> dict | None:
    return await get_db()[USERS].find_one({"email": email})


# ── Pre survey ─────────────────────────────────────────────────────────────────
async def save_pre_response(email: str, name: str, fields: dict) -> tuple[str, dict]:
    """Save pre-survey response. Returns (pre_id, updated_user)."""
    db = get_db(); now = _now()
    res = await db[PRE].insert_one(
        {"email": email, "name": name, "submitted_at": now, "fields": fields}
    )
    pre_id = str(res.inserted_id)
    user = await db[USERS].find_one_and_update(
        {"email": email},
        {"$set": {"status": STATUS_PRE_DONE, "pre_id": pre_id,
                  "pre_submitted_at": now, "updated_at": now,
                  "education_type": fields.get("A4", "")}},
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
    user = await db[USERS].find_one_and_update(
        {"email": email},
        {"$set": {"status": STATUS_POST_DONE, "post_id": post_id,
                  "post_submitted_at": now, "updated_at": now}},
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
    res = await get_db()[ORI].insert_one(
        {"email": email, "name": name, "submitted_at": now, "data": data}
    )
    await get_db()[USERS].update_one(
        {"email": email},
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
    if dept:
        query["program"] = dept
    if ug_or_pg:
        query["ug_or_pg"] = ug_or_pg

    result = []
    async for u in get_db()[USERS].find(query).sort("created_at", -1).limit(limit):
        email = u["email"]
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
            "education_type":      u.get("education_type", ""),
            "status":              u.get("status") or "not_started",
            "orientation_submitted": u.get("orientation_submitted", False),
            "pre_at":              _fmt(pre_sub),
            "post_at":             _fmt(post_sub),
            "orientation_at":      _fmt(u.get("orientation_at")),
            "pre_reminder_at":     _fmt(pre_reminder),
            "post_reminder_at":    _fmt(post_reminder),
            "reminder_clicked_at": _fmt(clicked),
            "completed_after_reminder": completed_after,
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
    if program:
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


async def get_dept_stats() -> list[dict]:
    """Return per-department stats: registered, pre_done, post_done counts."""
    db = get_db()
    pipeline = [
        {"$group": {
            "_id": "$program",
            "registered": {"$sum": 1},
            "pre_done":  {"$sum": {"$cond": [{"$in": ["$status", [STATUS_PRE_DONE, STATUS_POST_DONE]]}, 1, 0]}},
            "post_done": {"$sum": {"$cond": [{"$eq": ["$status", STATUS_POST_DONE]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    results = []
    res = db[USERS].aggregate(pipeline)
    import inspect
    if inspect.isawaitable(res):
        cursor = await res
    else:
        cursor = res
    async for doc in cursor:
        dept = doc["_id"] or ""
        results.append({
            "dept":       dept,
            "registered": doc["registered"],
            "pre_done":   doc["pre_done"],
            "post_done":  doc["post_done"],
            "pre_pending":  doc["registered"] - doc["pre_done"],
            "post_pending": doc["pre_done"] - doc["post_done"],
        })
    return results


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
