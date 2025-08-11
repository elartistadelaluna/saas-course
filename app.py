import os
import stripe
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

def monthly_image_usage(user_id: str) -> int:
    first_of_month = date.today().replace(day=1).isoformat()
    r = supabase.table("images").select("id", count="exact") \
        .eq("user_id", user_id) \
        .gte("created_at", first_of_month) \
        .execute()
    return int(r.count or 0)

def plan_limit(plan: str) -> int:
    return 20 if plan == "pro" else 4

# --- routes ------------------------------------------------------------------
@app.get("/api/me")
def me():
    user = get_user_from_auth_header()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    ensure_user_row_if_missing(user.id, getattr(user, "email", None))
    row = supabase.table("users").select("*").eq("id", user.id).single().execute().data or {}
    plan = row.get("plan", "free")
    used = monthly_image_usage(user.id)
    limit_ = plan_limit(plan)
    credits = max(limit_ - used, 0)

    return jsonify({
        "plan": plan,
        "credits": credits
    })

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

    def set_plan_by_status(customer_id: str, stripe_status: str):
        internal_status = "active" if stripe_status in ("active", "trialing") \
            else ("past_due" if stripe_status == "past_due" else "canceled")
        plan = "pro" if internal_status == "active" else "free"

        res = supabase.table("users").select("id").eq("stripe_customer_id", customer_id).single().execute()
        if not res.data:
            return
        uid = res.data["id"]
        supabase.table("users").update({
            "plan": plan,
            "subscription_status": internal_status
        }).eq("id", uid).execute()

    if et == "checkout.session.completed":
        uid = (obj.get("metadata") or {}).get("supabase_uid")
        if uid and obj.get("customer"):
            supabase.table("users").update({"stripe_customer_id": obj["customer"]}).eq("id", uid).execute()

    elif et in ("customer.subscription.created", "customer.subscription.updated"):
        set_plan_by_status(obj["customer"], obj.get("status", ""))

    elif et == "customer.subscription.deleted":
        set_plan_by_status(obj["customer"], "canceled")

    return jsonify({"received": True})

# --- entrypoint --------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
