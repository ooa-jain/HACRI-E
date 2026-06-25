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
async def upsert_user(email: str, name: str, program: str = "") -> dict:
    now = _now()
    return await get_db()[USERS].find_one_and_update(
        {"email": email},
        {
            "$set":       {"name": name, "program": program.strip(), "updated_at": now},
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
                  "pre_submitted_at": now, "updated_at": now}},
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


async def list_survey_users(limit: int = 10_000) -> list[dict]:
    import base64
    result = []
    async for u in get_db()[USERS].find({}).sort("created_at", -1).limit(limit):
        email = u["email"]
        slug = base64.urlsafe_b64encode(email.lower().encode()).rstrip(b"=").decode()
        result.append({
            "email":                email,
            "email_slug":           slug,
            "name":                 u.get("name", ""),
            "program":              u.get("program", ""),
            "status":               u.get("status") or "not_started",
            "orientation_submitted": u.get("orientation_submitted", False),
            "pre_at":               _fmt(u.get("pre_submitted_at")),
            "post_at":              _fmt(u.get("post_submitted_at")),
            "orientation_at":       _fmt(u.get("orientation_at")),
        })
    return result


async def list_orientation_responses(limit: int = 10_000) -> list[dict]:
    result = []
    async for doc in get_db()[ORI].find({}).sort("submitted_at", -1).limit(limit):
        result.append({
            "email":        doc.get("email", ""),
            "name":         doc.get("name", ""),
            "submitted_at": _fmt(doc.get("submitted_at")),
        })
    return result


async def list_matched_users(program: str | None = None, limit: int = 10_000) -> dict[str, dict]:
    """Return {email: {pre: fields, post: fields}} for users with both surveys done."""
    db = get_db()
    query = {"status": STATUS_POST_DONE}
    if program:
        query["program"] = program
    matched: dict[str, dict] = {}
    async for u in db[USERS].find(query).limit(limit):
        email = u["email"]
        pre  = await db[PRE ].find_one({"email": email}, sort=[("submitted_at", -1)])
        post = await db[POST].find_one({"email": email}, sort=[("submitted_at", -1)])
        if pre and post:
            matched[email] = {"pre": pre.get("fields", {}), "post": post.get("fields", {})}
    return matched


async def delete_user_and_responses(email: str) -> None:
    db = get_db()
    await db[USERS].delete_one({"email": email})
    await db[PRE].delete_many({"email": email})
    await db[POST].delete_many({"email": email})
    await db[ORI].delete_many({"email": email})
