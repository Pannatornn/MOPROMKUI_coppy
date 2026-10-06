from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import desc, func
from werkzeug.security import check_password_hash, generate_password_hash

from .ai import AIResult, generate_interview_turn
from .credentials import PROVIDERS, clear_api_key, credential_status, save_api_key
from .extensions import db, limiter
from .models import AuditEvent, Case, Message, StaffUser
from .prompts import PROMPT_VERSION
from .referrals import recommend_department
from .safety import (
    EMERGENCY_MESSAGE,
    REVIEW_MESSAGE,
    SAFE_FALLBACK_MESSAGE,
    URGENT_PAIN_MESSAGE,
    ai_message_is_safe,
    find_red_flags,
    find_urgent_signals,
)

bp = Blueprint("main", __name__)

AGE_GROUPS = {"0-12", "13-17", "18-39", "40-59", "60+", "unknown"}
SEX_OPTIONS = {"female", "male", "intersex", "prefer_not_to_say"}
PREGNANCY_OPTIONS = {"pregnant", "possibly_pregnant", "not_pregnant", "not_applicable", "unknown"}
URGENCY_OPTIONS = {"routine", "soon", "urgent", "emergency"}
STATUS_OPTIONS = {"collecting", "ready", "escalated", "closed"}
STAFF_ROLES = {"admin", "staff"}
MIN_PATIENT_TURNS = 8
MAX_PATIENT_TURNS = 12
DIRECT_IDENTIFIER = re.compile(r"(?:\b\d{13}\b|\b0\d{8,9}\b|[\w.+-]+@[\w-]+\.[\w.-]+)")
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_reference() -> str:
    while True:
        reference = f"MPK-{secrets.token_hex(4).upper()}"
        if not db.session.scalar(db.select(Case).where(Case.reference == reference)):
            return reference


def _json_error(message: str, status: int):
    return jsonify({"error": message}), status


def _case_for_patient(case_id: str) -> Case:
    case = db.session.get(Case, case_id)
    token = request.headers.get("X-Case-Token", "")
    if not case or not token or not hmac.compare_digest(case.token_hash, _hash_token(token)):
        abort(404)
    session['appointment_case_id'] = case.id
    session['appointment_case_hash'] = case.token_hash
    return case


def _case_json(case: Case, include_messages: bool = True) -> dict:
    latest_ai_event = next(
        (event for event in reversed(case.audit_events) if event.action == "interview_turn"),
        None,
    )
    if latest_ai_event:
        provider = latest_ai_event.detail.get("provider")
        ai_mode = "ai" if provider in {"gemini", "openai"} else "fallback"
    elif case.rule_urgency == "emergency":
        provider = None
        ai_mode = "safety_rule"
    else:
        provider = None
        ai_mode = "pending"
    data = {
        "id": case.id,
        "reference": case.reference,
        "status": case.status,
        "urgency": case.rule_urgency,
        "created_at": case.created_at.isoformat(),
        "ai_mode": ai_mode,
        "ai_provider": provider if ai_mode == "ai" else None,
        "appointment_referral": recommend_department(case),
    }
    if include_messages:
        data["messages"] = [
            {"role": message.role, "content": message.content, "created_at": message.created_at.isoformat()}
            for message in case.messages
        ]
    return data


def _audit(case: Case, actor: str, action: str, detail: dict | None = None) -> None:
    db.session.add(AuditEvent(case=case, actor=actor, action=action, detail=detail or {}))


def _apply_red_flags(case: Case, text: str) -> bool:
    new_flags = find_red_flags(text)
    if not new_flags:
        return False
    known = {item["code"] for item in (case.matched_red_flags or [])}
    case.matched_red_flags = (case.matched_red_flags or []) + [
        item for item in new_flags if item["code"] not in known
    ]
    case.rule_urgency = "emergency"
    case.status = "escalated"
    _audit(case, "safety_engine", "red_flag_matched", {"codes": [item["code"] for item in new_flags]})
    return True


def _apply_urgent_signals(case: Case, text: str) -> bool:
    new_signals = find_urgent_signals(text)
    if not new_signals:
        return False
    known = {item["code"] for item in (case.matched_red_flags or [])}
    case.matched_red_flags = (case.matched_red_flags or []) + [
        item for item in new_signals if item["code"] not in known
    ]
    if case.rule_urgency != "emergency":
        case.rule_urgency = "urgent"
    _audit(
        case,
        "safety_engine",
        "urgent_signal_matched",
        {"codes": [item["code"] for item in new_signals]},
    )
    return True


def _apply_ai_result(case: Case, result: AIResult) -> str:
    turn = result.turn
    case.ai_summary = turn.summary.model_dump()
    case.ai_urgency_suggestion = turn.urgency_suggestion

    patient_turns = sum(1 for message in case.messages if message.role == "patient")
    if turn.status == "escalate_review" or turn.red_flags_reported:
        case.status = "escalated"
        if case.rule_urgency != "emergency":
            case.rule_urgency = "urgent"
        output = REVIEW_MESSAGE
    elif patient_turns >= MAX_PATIENT_TURNS:
        case.status = "ready"
        output = (
            "ขอบคุณครับ ข้อมูลพร้อมให้บุคลากรทางการแพทย์ตรวจแล้ว "
            "หากอาการรุนแรงขึ้นหรือมีเหตุฉุกเฉินให้โทร 1669"
        )
    elif turn.status == "ready" and patient_turns >= MIN_PATIENT_TURNS:
        case.status = "ready"
        output = turn.assistant_message
    else:
        case.status = "collecting"
        if turn.status == "ready":
            output = turn.remaining_questions[0] if turn.remaining_questions else _fallback_question(case)
        else:
            output = turn.assistant_message

    if not ai_message_is_safe(output):
        output = SAFE_FALLBACK_MESSAGE
        case.status = "ready"
        _audit(case, "output_guard", "unsafe_ai_output_blocked")

    _audit(
        case,
        "ai",
        "interview_turn",
        {
            "provider": result.provider,
            "model": result.model or (
                current_app.config["OPENAI_MODEL"]
                if result.provider == "openai"
                else current_app.config["GEMINI_MODEL"]
                if result.provider == "gemini"
                else None
            ),
            "prompt_version": PROMPT_VERSION,
            "analysis_scope": "full_transcript_every_turn",
            "request_id": result.request_id,
            "error_code": result.error_code,
        },
    )
    return output


def _fallback_question(case: Case) -> str:
    from .ai import _fallback

    return _fallback(case, "minimum_history_not_met").turn.assistant_message


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _require_csrf() -> None:
    expected = session.get("_csrf_token", "")
    actual = request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected, actual):
        abort(400, "CSRF validation failed")


def _current_staff() -> StaffUser | None:
    user_id = session.get("staff_user_id")
    if not user_id:
        return None
    user = db.session.get(StaffUser, user_id)
    return user if user and user.is_active else None


def _staff_required(role: str | None = None) -> StaffUser:
    if not session.get("staff_authenticated"):
        abort(401)
    user = _current_staff()
    if user is None:
        session.clear()
        abort(401)
    if role and user.role != role:
        abort(403)
    return user


def _staff_actor(user: StaffUser) -> str:
    return f"staff:{user.username}"


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/intake")
def intake():
    return render_template("intake.html")


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.get("/healthz")
def healthz():
    db.session.execute(db.select(1))
    return jsonify({"status": "ok"})


@bp.post("/api/cases")
@limiter.limit("8 per minute")
def create_case():
    data = request.get_json(silent=True) or {}
    chief = str(data.get("chief_complaint", "")).strip()
    if data.get("consent") is not True:
        return _json_error("ต้องยอมรับประกาศความเป็นส่วนตัวก่อนเริ่ม", 400)
    if data.get("age_group") not in AGE_GROUPS:
        return _json_error("ช่วงอายุไม่ถูกต้อง", 400)
    if data.get("sex_at_birth") not in SEX_OPTIONS:
        return _json_error("ข้อมูลเพศกำเนิดไม่ถูกต้อง", 400)
    if data.get("pregnancy_status") not in PREGNANCY_OPTIONS:
        return _json_error("ข้อมูลการตั้งครรภ์ไม่ถูกต้อง", 400)
    if not 3 <= len(chief) <= 1500:
        return _json_error("กรุณาอธิบายอาการ 3-1,500 ตัวอักษร", 400)
    if DIRECT_IDENTIFIER.search(chief):
        return _json_error("กรุณาลบเลขบัตร เบอร์โทร หรืออีเมลออกจากข้อความ", 400)

    token = secrets.token_urlsafe(32)
    case = Case(
        reference=_new_reference(),
        token_hash=_hash_token(token),
        age_group=data["age_group"],
        sex_at_birth=data["sex_at_birth"],
        pregnancy_status=data["pregnancy_status"],
        chief_complaint=chief,
        consent_version=current_app.config["CONSENT_VERSION"],
        consent_at=datetime.now(timezone.utc),
    )
    db.session.add(case)
    db.session.add(Message(case=case, role="patient", content=chief))
    _audit(case, "patient", "consent_recorded", {"version": case.consent_version})
    db.session.flush()

    if _apply_red_flags(case, chief):
        assistant_text = EMERGENCY_MESSAGE
    elif _apply_urgent_signals(case, chief):
        assistant_text = (
            f"{URGENT_PAIN_MESSAGE}\n\n"
            f"{_apply_ai_result(case, generate_interview_turn(case))}"
        )
    else:
        assistant_text = _apply_ai_result(case, generate_interview_turn(case))
    db.session.add(Message(case=case, role="assistant", content=assistant_text))
    db.session.commit()

    payload = _case_json(case)
    session['appointment_case_id'] = case.id
    session['appointment_case_hash'] = case.token_hash
    payload["token"] = token
    return jsonify(payload), 201


@bp.get("/api/cases/<case_id>")
@limiter.limit("30 per minute")
def get_case(case_id: str):
    return jsonify(_case_json(_case_for_patient(case_id)))


@bp.post("/api/cases/<case_id>/messages")
@limiter.limit("15 per minute")
def add_message(case_id: str):
    case = _case_for_patient(case_id)
    if case.status == "closed":
        return _json_error("เคสนี้ปิดแล้ว", 409)
    if case.rule_urgency == "emergency":
        return jsonify(_case_json(case)), 409

    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    if not 1 <= len(content) <= 2000:
        return _json_error("ข้อความต้องมี 1-2,000 ตัวอักษร", 400)
    if DIRECT_IDENTIFIER.search(content):
        return _json_error("กรุณาลบเลขบัตร เบอร์โทร หรืออีเมลออกจากข้อความ", 400)

    db.session.add(Message(case=case, role="patient", content=content))
    db.session.flush()
    if _apply_red_flags(case, content):
        assistant_text = EMERGENCY_MESSAGE
    elif _apply_urgent_signals(case, content):
        assistant_text = (
            f"{URGENT_PAIN_MESSAGE}\n\n"
            f"{_apply_ai_result(case, generate_interview_turn(case))}"
        )
    else:
        assistant_text = _apply_ai_result(case, generate_interview_turn(case))
    db.session.add(Message(case=case, role="assistant", content=assistant_text))
    db.session.commit()
    return jsonify(_case_json(case))


@bp.route("/staff/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def staff_login():
    error = None
    if request.method == "POST":
        _require_csrf()
        username = request.form.get("username", "").strip().casefold()
        user = db.session.scalar(db.select(StaffUser).where(StaffUser.username == username))
        password_ok = bool(user and user.is_active) and check_password_hash(
            user.password_hash, request.form.get("password", "")
        )
        if user and password_ok:
            session.clear()
            session["staff_authenticated"] = True
            session["staff_user_id"] = user.id
            session["staff_role"] = user.role
            session["staff_display_name"] = user.display_name
            session["_csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            return redirect(url_for("main.staff_dashboard"))
        error = "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
    return render_template("staff_login.html", error=error)


@bp.post("/staff/logout")
def staff_logout():
    _staff_required()
    _require_csrf()
    session.clear()
    return redirect(url_for("main.staff_login"))


@bp.get("/staff")
def staff_dashboard():
    staff_user = _staff_required()
    cases = db.session.scalars(db.select(Case).order_by(desc(Case.created_at)).limit(100)).all()
    return render_template("staff_dashboard.html", cases=cases, staff_user=staff_user)


@bp.get("/staff/cases/<case_id>")
def staff_case(case_id: str):
    staff_user = _staff_required()
    case = db.get_or_404(Case, case_id)
    _audit(case, _staff_actor(staff_user), "case_viewed")
    db.session.commit()
    return render_template("staff_case.html", case=case)


@bp.post("/staff/cases/<case_id>/review")
def staff_review_case(case_id: str):
    staff_user = _staff_required()
    _require_csrf()
    case = db.get_or_404(Case, case_id)
    urgency = request.form.get("urgency", "")
    status = request.form.get("status", "")
    if urgency not in URGENCY_OPTIONS or status not in STATUS_OPTIONS:
        abort(400)
    case.clinician_urgency = urgency
    case.status = status
    _audit(
        case,
        _staff_actor(staff_user),
        "clinical_review_updated",
        {"urgency": urgency, "status": status},
    )
    db.session.commit()
    return redirect(url_for("main.staff_case", case_id=case.id))


@bp.post("/staff/cases/<case_id>/delete")
def staff_delete_case(case_id: str):
    _staff_required("admin")
    _require_csrf()
    case = db.get_or_404(Case, case_id)
    if request.form.get("confirm_reference") != case.reference:
        abort(400, "Reference confirmation failed")
    db.session.delete(case)
    db.session.commit()
    return redirect(url_for("main.staff_dashboard"))


@bp.route("/staff/users", methods=["GET", "POST"])
def staff_users():
    current_user = _staff_required("admin")
    error = None
    if request.method == "POST":
        _require_csrf()
        username = request.form.get("username", "").strip().casefold()
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        if not USERNAME_PATTERN.fullmatch(username):
            error = "ชื่อผู้ใช้ต้องมี 3–32 ตัว และใช้ a-z, 0-9, จุด, ขีดกลาง หรือขีดล่าง"
        elif not 2 <= len(display_name) <= 80:
            error = "ชื่อที่แสดงต้องมี 2–80 ตัวอักษร"
        elif role not in STAFF_ROLES:
            error = "บทบาทไม่ถูกต้อง"
        elif not 12 <= len(password) <= 128:
            error = "รหัสผ่านต้องมี 12–128 ตัวอักษร"
        elif db.session.scalar(db.select(StaffUser).where(StaffUser.username == username)):
            error = "ชื่อผู้ใช้นี้มีอยู่แล้ว"
        else:
            db.session.add(
                StaffUser(
                    username=username,
                    display_name=display_name,
                    password_hash=generate_password_hash(password, method="scrypt"),
                    role=role,
                    is_active=True,
                )
            )
            db.session.commit()
            flash(f"สร้างบัญชี {username} แล้ว", "success")
            return redirect(url_for("main.staff_users"))

    users = db.session.scalars(db.select(StaffUser).order_by(StaffUser.created_at)).all()
    return render_template(
        "staff_users.html", users=users, current_user=current_user, error=error
    )


@bp.route("/staff/ai-settings", methods=["GET", "POST"])
def staff_ai_settings():
    current_user = _staff_required("admin")
    if request.method == "POST":
        _require_csrf()
        provider = request.form.get("provider", "")
        action = request.form.get("action", "save")
        if provider not in PROVIDERS:
            abort(400, "Unknown AI provider")
        if action == "clear":
            if clear_api_key(provider):
                flash(f"ลบ API key สำรองของ {provider.upper()} แล้ว ระบบจะกลับไปใช้ค่าจาก Render", "success")
            else:
                flash(f"ยังไม่มี API key สำรองของ {provider.upper()}", "error")
        elif action == "save":
            api_key = request.form.get("api_key", "").strip()
            if not 16 <= len(api_key) <= 512 or any(character.isspace() for character in api_key):
                flash("API key ต้องมี 16–512 ตัวอักษรและไม่มีช่องว่าง", "error")
            else:
                save_api_key(provider, api_key, current_user.username)
                flash(f"บันทึก API key ใหม่สำหรับ {provider.upper()} แล้ว", "success")
        else:
            abort(400, "Unknown settings action")
        return redirect(url_for("main.staff_ai_settings"))

    credentials = {provider: credential_status(provider) for provider in sorted(PROVIDERS)}
    return render_template(
        "staff_ai_settings.html",
        current_user=current_user,
        credentials=credentials,
        active_provider=current_app.config["AI_PROVIDER"],
    )


@bp.post("/staff/users/<int:user_id>/toggle")
def staff_user_toggle(user_id: int):
    current_user = _staff_required("admin")
    _require_csrf()
    target = db.get_or_404(StaffUser, user_id)
    if target.id == current_user.id:
        abort(400, "Cannot disable your own account")
    if target.is_active and target.role == "admin":
        active_admins = db.session.scalar(
            db.select(func.count()).select_from(StaffUser).where(
                StaffUser.role == "admin", StaffUser.is_active.is_(True)
            )
        )
        if active_admins is not None and active_admins <= 1:
            abort(400, "At least one active admin is required")
    target.is_active = not target.is_active
    db.session.commit()
    flash(
        f"{'เปิด' if target.is_active else 'ระงับ'}บัญชี {target.username} แล้ว",
        "success",
    )
    return redirect(url_for("main.staff_users"))


@bp.post("/staff/users/<int:user_id>/password")
def staff_user_password(user_id: int):
    _staff_required("admin")
    _require_csrf()
    target = db.get_or_404(StaffUser, user_id)
    password = request.form.get("password", "")
    if not 12 <= len(password) <= 128:
        flash("รหัสผ่านต้องมี 12–128 ตัวอักษร", "error")
    else:
        target.password_hash = generate_password_hash(password, method="scrypt")
        db.session.commit()
        flash(f"ตั้งรหัสผ่านใหม่ให้ {target.username} แล้ว", "success")
    return redirect(url_for("main.staff_users"))


def init_app(app):
    app.register_blueprint(bp)
    app.jinja_env.globals["csrf_token"] = _csrf_token
