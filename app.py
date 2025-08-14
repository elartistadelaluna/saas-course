import os
import uuid
import stripe
import requests
from pathlib import Path
from urllib.parse import urlparse, unquote
from datetime import datetime, date
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
from dotenv import load_dotenv

# --- env & clients -----------------------------------------------------------
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://gptsweetheart.com")

STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
STRIPE_PRICE_ID_PRO = os.environ["STRIPE_PRICE_ID_PRO"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

# new
N8N_WORKFLOW_URL = os.environ["N8N_WORKFLOW_URL"]
N8N_CALLBACK_SECRET = os.environ["N8N_CALLBACK_SECRET"]
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/var/www/gptsweetheart/media")
N8N_IMAGE_WORKFLOW_URL = os.environ["N8N_IMAGE_WORKFLOW_URL"]
N8N_CHAT_WEBHOOK_URL = os.environ.get("N8N_CHAT_WEBHOOK_URL") 

stripe.api_key = STRIPE_SECRET_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- helpers -----------------------------------------------------------------
def get_user_from_auth_header():
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        user = supabase.auth.get_user(token)
        return user.user
    except Exception:
        return None

def ensure_user_row_if_missing(user_id: str, email: str | None = None):
    res = supabase.table("users").select("id").eq("id", user_id).execute()
    if not res.data:
        supabase.table("users").insert({
            "id": user_id,
            "plan": "free",
            "created_at": datetime.utcnow().isoformat()
        }).execute()

def images_count_since(user_id: str, since_iso: str | None) -> int:
    """
    Count billable images for a user since a given ISO timestamp.
    Excludes the initial influencer image (is_initial = True).
    """
    q = supabase.table("images").select("id", count="exact") \
        .eq("user_id", user_id) \
        .eq("is_initial", False)
    if since_iso:
        q = q.gte("created_at", since_iso)
    r = q.execute()
    return int(r.count or 0)


def save_image_to_media(image_url: str, user_id: str, filename_prefix: str = "img_") -> tuple[str, str]:
    """Downloads image to MEDIA_ROOT/<user_id>/<prefix><uuid>.<ext>.
    Returns (abs_path, public_url)."""
    resp = requests.get(image_url, timeout=90)
    resp.raise_for_status()
    folder = Path(MEDIA_ROOT) / user_id
    folder.mkdir(parents=True, exist_ok=True)

    # figure out extension
    name = Path(unquote(urlparse(image_url).path)).name.lower()
    ext = Path(name).suffix
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"

    fname = f"{filename_prefix}{uuid.uuid4().hex}{ext}"
    abs_path = folder / fname
    with open(abs_path, "wb") as f:
        f.write(resp.content)
    public_url = f"{FRONTEND_URL}/media/{user_id}/{fname}"
    return str(abs_path), public_url


def trigger_n8n_influencer_setup(payload: dict):
    # Pass a header so the workflow can forward the same secret to our callback.
    headers = {"Content-Type": "application/json"}
    requests.post(N8N_WORKFLOW_URL, json=payload, headers=headers, timeout=30)
    

def trigger_n8n_image_create(payload: dict):
    headers = {"Content-Type": "application/json"}
    requests.post(N8N_IMAGE_WORKFLOW_URL, json=payload, headers=headers, timeout=60)

def trigger_n8n_chat(payload: dict):
    """Send chat payload to n8n which will call back with an AI reply."""
    headers = {"Content-Type": "application/json"}
    requests.post(N8N_CHAT_WEBHOOK_URL, json=payload, headers=headers, timeout=60)

def _utc_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()

def ensure_chat(user_id: str, influencer_id: str) -> dict:
    """Return an existing chat row or create a new one."""
    ch = supabase.table("chats").select("*") \
        .eq("user_id", user_id).eq("influencer_id", influencer_id) \
        .limit(1).execute().data
    if ch:
        return ch[0]
    now_iso = _utc_iso(datetime.utcnow())
    created = supabase.table("chats").insert({
        "user_id": user_id,
        "influencer_id": influencer_id,
        "created_at": now_iso
    }).execute().data[0]
    return created

def maybe_seed_first_ai_message(user_id: str, influencer_id: str, chat_id: str):
    """
    Proactive first AI message ~10s after influencer creation.
    We do this lazily: when the client asks for chat, we check if:
      - influencer is locked
      - no messages exist for the chat
      - influencer.created_at is at least 10s in the past
    If so, we insert the opener from the AI.
    """
    # any message already?
    msg_count = supabase.table("messages").select("id", count="exact") \
        .eq("chat_id", chat_id).execute().count or 0
    if msg_count and msg_count > 0:
        return

    inf = supabase.table("influencers").select("created_at") \
        .eq("id", influencer_id).single().execute().data
    if not inf or not inf.get("created_at"):
        return

    try:
        created = datetime.fromisoformat(inf["created_at"].replace("Z", "+00:00"))
    except Exception:
        return

    if (datetime.utcnow() - created).total_seconds() < 10:
        return

    # seed AI opener
    opener = "Hi sweetheart, how are you today? Why don’t you tell me your name and how your day is going?;)"
    supabase.table("messages").insert({
        "chat_id": chat_id,
        "role": "assistant",
        "content": opener,
        "created_at": _utc_iso(datetime.utcnow())
    }).execute()

def last_messages(chat_id: str, limit: int = 20) -> list[dict]:
    rows = supabase.table("messages").select("id,role,content,created_at") \
        .eq("chat_id", chat_id) \
        .order("created_at", desc=True) \
        .limit(limit).execute().data or []
    # return oldest→newest for rendering
    return list(reversed(rows))

def today_user_message_count(chat_id: str) -> int:
    # count only user's messages since UTC midnight
    midnight = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    r = supabase.table("messages").select("id", count="exact") \
        .eq("chat_id", chat_id).eq("role", "user") \
        .gte("created_at", _utc_iso(midnight)).execute()
    return int(r.count or 0)

@app.get("/api/me")
def me():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    ensure_user_row_if_missing(user.id, getattr(user, "email", None))
    row = supabase.table("users").select("*").eq("id", user.id).single().execute().data or {}

    plan = row.get("plan", "free")
    if plan == "pro":
        # Stripe period–based credits. If period not yet stored, show full 20.
        period_start = row.get("subscription_period_start")
        if period_start:
            used = images_count_since(user.id, period_start)
        else:
            used = 0
        credits = max(20 - used, 0)
    else:
        # Free = one-time bucket stored on the user row (default 3)
        credits = max(int(row.get("free_grant_remaining", 3)), 0)

    return jsonify({"plan": plan, "credits": credits})


@app.post("/api/upgrade")
def upgrade():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    ensure_user_row_if_missing(user.id, getattr(user, "email", None))
    u = supabase.table("users").select("*").eq("id", user.id).single().execute().data
    customer_id = u.get("stripe_customer_id") if u else None

    if not customer_id:
        customer = stripe.Customer.create(
            email=getattr(user, "email", None),
            metadata={"supabase_uid": user.id}
        )
        customer_id = customer["id"]
        supabase.table("users").update({"stripe_customer_id": customer_id}).eq("id", user.id).execute()

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        customer=customer_id,
        line_items=[{"price": STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=f"{FRONTEND_URL}/dashboard?upgraded=1",
        cancel_url=f"{FRONTEND_URL}/dashboard?cancelled=1",
        metadata={"supabase_uid": user.id},
    )
    return jsonify({"url": session.url})

@app.post("/api/billing-portal")
def billing_portal():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    u = supabase.table("users").select("stripe_customer_id").eq("id", user.id).single().execute().data
    customer_id = (u or {}).get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(
            email=getattr(user, "email", None),
            metadata={"supabase_uid": user.id}
        )
        customer_id = customer["id"]
        supabase.table("users").update({"stripe_customer_id": customer_id}).eq("id", user.id).execute()

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{FRONTEND_URL}/dashboard"
    )
    return jsonify({"url": portal.url})

@app.post("/api/stripe/webhook")
def stripe_webhook():
    payload = request.data
    sig = request.headers.get("Stripe-Signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    et = event["type"]
    obj = event["data"]["object"]

    def set_plan_by_status(customer_id: str, stripe_status: str, sub_obj=None):
        internal_status = "active" if stripe_status in ("active", "trialing") \
            else ("past_due" if stripe_status == "past_due" else "canceled")
        plan = "pro" if internal_status == "active" else "free"

        res = supabase.table("users").select("id").eq("stripe_customer_id", customer_id).single().execute()
        if not res.data:
            return
        uid = res.data["id"]

        update = {
            "plan": plan,
            "subscription_status": internal_status
        }

        # --- NEW: robust extraction of current period (top-level or first item) ---
        cps = cpe = None
        if sub_obj:
            cps = sub_obj.get("current_period_start")
            cpe = sub_obj.get("current_period_end")
            if not cps or not cpe:
                items = (sub_obj.get("items") or {}).get("data") or []
                if items:
                    cps = cps or items[0].get("current_period_start")
                    cpe = cpe or items[0].get("current_period_end")
        # --------------------------------------------------------------------------

        if cps and cpe and plan == "pro":
            from_ts = datetime.utcfromtimestamp(int(cps)).isoformat()
            to_ts   = datetime.utcfromtimestamp(int(cpe)).isoformat()
            update["subscription_period_start"] = from_ts
            update["subscription_period_end"]   = to_ts
        elif plan != "pro":
            # Clear period fields when not active
            update["subscription_period_start"] = None
            update["subscription_period_end"] = None

        supabase.table("users").update(update).eq("id", uid).execute()

    if et == "checkout.session.completed":
        uid = (obj.get("metadata") or {}).get("supabase_uid")
        if uid and obj.get("customer"):
            supabase.table("users").update({"stripe_customer_id": obj["customer"]}).eq("id", uid).execute()

    elif et in ("customer.subscription.created", "customer.subscription.updated"):
        set_plan_by_status(obj["customer"], obj.get("status", ""), obj)

    elif et == "customer.subscription.deleted":
        set_plan_by_status(obj["customer"], "canceled", obj)

    return jsonify({"received": True})


# --- routes: influencer ------------------------------------------------------

@app.get("/api/influencer")
def get_influencer():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    res = supabase.table("influencers").select(
        "id,name,bio,vibe,base_prompt,seed,initial_image_url,is_locked,created_at"
    ).eq("user_id", user.id).limit(1).execute()

    if not res.data:
        return jsonify({"influencer": None})

    return jsonify({"influencer": res.data[0]})

@app.post("/api/influencer")
def create_influencer():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    ensure_user_row_if_missing(user.id, getattr(user, "email", None))

    # Enforce one-per-user
    existing = supabase.table("influencers").select("id").eq("user_id", user.id).limit(1).execute()
    if existing.data:
        return jsonify({"error": "influencer_exists"}), 409

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    bio = (body.get("bio") or "").strip()
    vibe = (body.get("vibe") or "").strip()
    if not name or not bio or not vibe:
        return jsonify({"error": "missing_fields"}), 400

    # Insert shell row (unlocked until finalized)
    insert = supabase.table("influencers").insert({
        "user_id": user.id,
        "name": name,
        "bio": bio,
        "vibe": vibe,
        "is_locked": False
    }).execute()

    influencer_id = insert.data[0]["id"]

    # Kick off n8n workflow
    callback_url = f"{FRONTEND_URL}/api/influencer/finalize"
    payload = {
        "user_id": user.id,
        "influencer_id": influencer_id,
        "name": name,
        "bio": bio,
        "vibe": vibe,
        "callback_url": callback_url,
        "callback_secret": N8N_CALLBACK_SECRET
    }
    try:
        trigger_n8n_influencer_setup(payload)
    except Exception as e:
        # If n8n call fails, remove the shell row so user can retry
        supabase.table("influencers").delete().eq("id", influencer_id).execute()
        return jsonify({"error": f"n8n_unreachable: {e}"}), 502

    return jsonify({"status": "queued", "influencer_id": influencer_id}), 202


@app.post("/api/influencer/finalize")
def finalize_influencer():
    # n8n → Flask callback
    secret = request.headers.get("X-Callback-Secret", "") or (request.json or {}).get("callback_secret", "")
    if secret != N8N_CALLBACK_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    influencer_id = data.get("influencer_id")
    base_prompt = data.get("base_prompt")
    seed = data.get("seed")
    replicate_image_url = data.get("image_url")

    if not influencer_id or not base_prompt or seed is None or not replicate_image_url:
        return jsonify({"error": "missing_fields"}), 400

    # Get owner
    row = supabase.table("influencers").select("user_id").eq("id", influencer_id).single().execute().data
    if not row:
        return jsonify({"error": "unknown_influencer"}), 404
    user_id = row["user_id"]

    # Save image to /media/<user_id>/...
    try:
        _, public_url = save_image_to_media(replicate_image_url, user_id, filename_prefix="initial_")
    except Exception as e:
        return jsonify({"error": f"image_download_failed: {e}"}), 500

    now_iso = datetime.utcnow().isoformat()

    # Update influencer (lock + store assets)
    supabase.table("influencers").update({
        "base_prompt": base_prompt,
        "seed": seed,
        "initial_image_url": public_url,
        "is_locked": True,
        "created_at": now_iso
    }).eq("id", influencer_id).execute()
    try:
        ensure_chat(user_id, influencer_id)
    except Exception:
        pass
        
    # Record the initial image for history/preview, but mark as non-billable
    supabase.table("images").insert({
        "user_id": user_id,
        "influencer_id": influencer_id,
        "prompt_final": base_prompt,
        "url": public_url,
        "created_at": now_iso,
        "is_initial": True
    }).execute()

    return jsonify({"ok": True})

@app.post("/api/images/create")
def create_more_images():
    """
    Creates a new (non-initial) image for the user's locked influencer.
    Enforces credits server-side:
      - free: must have free_grant_remaining > 0
      - pro: must have < 20 billable images in current period (excludes is_initial)
    Body: { "prompt": "..." }
    """
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # load user record (plan, free credits, period start)
    u = supabase.table("users").select("*").eq("id", user.id).single().execute().data or {}
    plan = u.get("plan", "free")

    # require a locked influencer
    inf = supabase.table("influencers").select(
        "id,name,bio,vibe,base_prompt,seed,is_locked"
    ).eq("user_id", user.id).single().execute().data
    if not inf or not inf.get("is_locked"):
        return jsonify({"error": "no_locked_influencer"}), 400

    body = request.get_json(silent=True) or {}
    user_prompt = (body.get("prompt") or "").strip()
    if not user_prompt:
        return jsonify({"error": "missing_prompt"}), 400

    # --- credit checks ---
    if plan == "pro":
        period_start = u.get("subscription_period_start")
        used = images_count_since(user.id, period_start)  # excludes is_initial
        if used >= 20:
            return jsonify({"error": "no_credits"}), 402  # Payment Required semantics
    else:
        free_left = int(u.get("free_grant_remaining", 3))
        if free_left <= 0:
            return jsonify({"error": "no_credits"}), 402

    # trigger n8n image workflow
    callback_url = f"{FRONTEND_URL}/api/images/finalize"
    payload = {
        "user_id": user.id,
        "influencer_id": inf["id"],
        "base_prompt": inf.get("base_prompt") or "",   # your base prompt
        "seed": inf.get("seed"),
        "bio": inf.get("bio") or "",
        "vibe": inf.get("vibe") or "",
        "user_prompt": user_prompt,
        "callback_url": callback_url,
        "callback_secret": N8N_CALLBACK_SECRET
    }
    try:
        trigger_n8n_image_create(payload)
    except Exception as e:
        return jsonify({"error": f"n8n_unreachable: {e}"}), 502

    return jsonify({"status": "queued"}), 202

@app.post("/api/images/finalize")
def finalize_generated_image():
    secret = request.headers.get("X-Callback-Secret", "") or (request.json or {}).get("callback_secret", "")
    if secret != N8N_CALLBACK_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    influencer_id = data.get("influencer_id")
    replicate_image_url = data.get("image_url")

    if not influencer_id or not replicate_image_url:
        return jsonify({"error": "missing_fields"}), 400

    # find owner
    row = supabase.table("influencers").select("user_id,base_prompt").eq("id", influencer_id).single().execute().data
    if not row:
        return jsonify({"error": "unknown_influencer"}), 404
    user_id = row["user_id"]
    base_prompt = row.get("base_prompt") or ""

    # persist image
    try:
        _, public_url = save_image_to_media(replicate_image_url, user_id)  # default prefix "img_"
    except Exception as e:
        return jsonify({"error": f"image_download_failed: {e}"}), 500

    now_iso = datetime.utcnow().isoformat()

    # store in images (non-initial)
    supabase.table("images").insert({
        "user_id": user_id,
        "influencer_id": influencer_id,
        "prompt_final": base_prompt,   # (you can enrich with user_prompt via n8n later)
        "url": public_url,
        "created_at": now_iso,
        "is_initial": False
    }).execute()

    # If user is on free plan at this moment, decrement free_grant_remaining
    u = supabase.table("users").select("plan,free_grant_remaining").eq("id", user_id).single().execute().data or {}
    if (u.get("plan") or "free") != "pro":
        left = max(int(u.get("free_grant_remaining", 0)) - 1, 0)
        supabase.table("users").update({"free_grant_remaining": left}).eq("id", user_id).execute()

    return jsonify({"ok": True})

@app.get("/api/images")
def list_images():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # get their influencer id
    inf = supabase.table("influencers").select("id").eq("user_id", user.id).single().execute().data
    if not inf:
        return jsonify({"images": []})

    rows = supabase.table("images").select("id,url,created_at,is_initial") \
        .eq("user_id", user.id) \
        .eq("influencer_id", inf["id"]) \
        .eq("is_initial", False) \
        .order("created_at", desc=True).execute().data or []

    return jsonify({"images": rows})

@app.get("/api/chat")
def get_chat():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # Need a locked influencer
    inf = supabase.table("influencers").select("id,is_locked,name,bio,vibe") \
        .eq("user_id", user.id).single().execute().data
    if not inf or not inf.get("is_locked"):
        return jsonify({
            "chat": None,
            "messages": [],
            "can_send": False,
            "daily_limit": 20,
            "sent_today": 0
        })

    # Ensure chat exists for this influencer
    try:
        chat = ensure_chat(user.id, inf["id"])
    except Exception:
        # If ensure_chat fails for any reason, create a basic chat record manually
        supabase.table("chats").insert({
            "user_id": user.id,
            "influencer_id": inf["id"],
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        chat = ensure_chat(user.id, inf["id"])

    # Lazily seed opener ~10s after creation if empty
    try:
        maybe_seed_first_ai_message(user.id, inf["id"], chat["id"])
    except Exception:
        pass  # Don't block chat load if seeding fails

    msgs = last_messages(chat["id"], limit=20)
    sent_today = today_user_message_count(chat["id"])
    can_send = sent_today < 20

    return jsonify({
        "chat": {"id": chat["id"], "influencer_id": inf["id"]},
        "influencer": {
            "name": inf.get("name"),
            "bio": inf.get("bio"),
            "vibe": inf.get("vibe")
        },
        "messages": msgs,
        "daily_limit": 20,
        "sent_today": sent_today,
        "can_send": can_send
    })

@app.post("/api/chat/message")
def chat_send_message():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "missing_content"}), 400

    # must have locked influencer
    inf = supabase.table("influencers").select("id,name,bio,vibe,is_locked") \
        .eq("user_id", user.id).single().execute().data
    if not inf or not inf.get("is_locked"):
        return jsonify({"error": "no_locked_influencer"}), 400

    chat = ensure_chat(user.id, inf["id"])

    # soft limit (front-end enforces, but re-check to be safe)
    if today_user_message_count(chat["id"]) >= 20:
        return jsonify({"error": "daily_limit_reached"}), 429

    # store the user's message
    now_iso = _utc_iso(datetime.utcnow())
    supabase.table("messages").insert({
        "chat_id": chat["id"],
        "role": "user",
        "content": content,
        "created_at": now_iso
    }).execute()

    # Prepare last 20 messages for n8n
    msgs = last_messages(chat["id"], limit=20)

    # trigger n8n to generate the assistant reply
    callback_url = f"{FRONTEND_URL}/api/chat/finalize"
    payload = {
        "chat_id": chat["id"],
        "user_id": user.id,
        "influencer_id": inf["id"],
        "influencer": {"name": inf.get("name"), "bio": inf.get("bio"), "vibe": inf.get("vibe")},
        "messages": msgs,
        "callback_url": callback_url,
        "callback_secret": N8N_CALLBACK_SECRET
    }
    try:
        trigger_n8n_chat(payload)
    except Exception as e:
        return jsonify({"error": f"n8n_unreachable: {e}"}), 502

    return jsonify({"status": "queued"})

@app.post("/api/chat/finalize")
def chat_finalize():
    secret = request.headers.get("X-Callback-Secret", "") or (request.json or {}).get("callback_secret", "")
    if secret != N8N_CALLBACK_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id")
    reply = (data.get("reply") or "").strip()
    if not chat_id or not reply:
        return jsonify({"error": "missing_fields"}), 400

    supabase.table("messages").insert({
        "chat_id": chat_id,
        "role": "assistant",
        "content": reply,
        "created_at": _utc_iso(datetime.utcnow())
    }).execute()

    return jsonify({"ok": True})


# --- entrypoint --------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
