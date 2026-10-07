"""Anonymous demo appointments with independent doctor calendars."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import secrets
import hmac

import click
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import ForeignKey, UniqueConstraint, update, case as sql_case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db, limiter
from .routes import _require_csrf, _staff_required
from .models import Case, AuditEvent
from .referrals import recommend_department, DEPARTMENTS

BANGKOK = timezone(timedelta(hours=7))
bp = Blueprint("appointments", __name__)
MONTHS = "มกราคม กุมภาพันธ์ มีนาคม เมษายน พฤษภาคม มิถุนายน กรกฎาคม สิงหาคม กันยายน ตุลาคม พฤศจิกายน ธันวาคม".split()
DEMO_DOCTORS = [
    ("demo-mint", "พญ.มินตรา", "เวชปฏิบัติทั่วไป", {0, 2, 4}, 9, 12, "จันทร์ · พุธ · ศุกร์ 09:00–12:00"),
    ("demo-nont", "นพ.นนทกร", "อายุรกรรม", {1, 3}, 13, 16, "อังคาร · พฤหัสบดี 13:00–16:00"),
    ("demo-pim", "พญ.พิมพ์ชนก", "ผิวหนัง", {2, 5}, 10, 14, "พุธ · เสาร์ 10:00–14:00"),
    ("demo-general-2", "นพ.ธนา", "เวชปฏิบัติทั่วไป", {1, 3, 5}, 13, 16, "อังคาร · พฤหัสบดี · เสาร์ 13:00–16:00"),
    ("demo-medicine-2", "พญ.กมล", "อายุรกรรม", {0, 2, 4}, 9, 12, "จันทร์ · พุธ · ศุกร์ 09:00–12:00"),
    ("demo-skin-2", "นพ.ปกรณ์", "ผิวหนัง", {1, 4}, 13, 16, "อังคาร · ศุกร์ 13:00–16:00"),
    ("demo-ortho-1", "นพ.ภัทร", "กระดูกและข้อ", {0, 3}, 9, 12, "จันทร์ · พฤหัสบดี 09:00–12:00"),
    ("demo-ortho-2", "พญ.ณิชา", "กระดูกและข้อ", {2, 5}, 13, 16, "พุธ · เสาร์ 13:00–16:00"),
    ("demo-ent-1", "นพ.วริน", "หู คอ จมูก", {1, 4}, 9, 12, "อังคาร · ศุกร์ 09:00–12:00"),
    ("demo-ent-2", "พญ.รินรดา", "หู คอ จมูก", {0, 3}, 13, 16, "จันทร์ · พฤหัสบดี 13:00–16:00"),
    ("demo-gyn-1", "พญ.ลลิตา", "สูติ–นรีเวช", {0, 2}, 9, 12, "จันทร์ · พุธ 09:00–12:00"),
    ("demo-gyn-2", "พญ.ชลธิชา", "สูติ–นรีเวช", {3, 5}, 13, 16, "พฤหัสบดี · เสาร์ 13:00–16:00"),
    ("demo-peds-1", "พญ.ชญา", "กุมารเวช", {1, 3}, 9, 12, "อังคาร · พฤหัสบดี 09:00–12:00"),
    ("demo-peds-2", "นพ.นที", "กุมารเวช", {2, 5}, 13, 16, "พุธ · เสาร์ 13:00–16:00"),
]


class Doctor(db.Model):
    __tablename__ = "appointment_doctors"
    id: Mapped[str] = mapped_column(db.String(32), primary_key=True)
    name: Mapped[str] = mapped_column(db.String(80))
    specialty: Mapped[str] = mapped_column(db.String(80))
    schedule_label: Mapped[str] = mapped_column(db.String(160))


class AppointmentSlot(db.Model):
    __tablename__ = "appointment_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("appointment_doctors.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), index=True)
    state: Mapped[str] = mapped_column(db.String(16), default="free")
    doctor: Mapped[Doctor] = relationship()
    __table_args__ = (UniqueConstraint("doctor_id", "starts_at", name="uq_doctor_slot"),)


class Appointment(db.Model):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(db.String(16), unique=True)
    owner_hash: Mapped[str] = mapped_column(db.String(64), index=True)
    # NULL after cancellation releases the unique active reservation.
    slot_id: Mapped[int | None] = mapped_column(ForeignKey("appointment_slots.id"), unique=True, nullable=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("appointment_doctors.id"))
    starts_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(db.String(16), default="booked")
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    doctor: Mapped[Doctor] = relationship()
    referral: Mapped['AppointmentReferral | None'] = relationship(back_populates='appointment', cascade='all, delete-orphan', uselist=False)


class AppointmentReferral(db.Model):
    __tablename__ = 'appointment_referrals'
    appointment_id: Mapped[int] = mapped_column(ForeignKey('appointments.id'), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey('cases.id', ondelete='SET NULL'), nullable=True)
    department: Mapped[str] = mapped_column(db.String(32))
    reason: Mapped[str] = mapped_column(db.String(260))
    appointment: Mapped[Appointment] = relationship(back_populates='referral')
    case: Mapped[Case | None] = relationship()


class AppointmentRequest(db.Model):
    __tablename__ = 'appointment_requests'
    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True)
    reference: Mapped[str] = mapped_column(db.String(16), unique=True)
    owner_hash: Mapped[str] = mapped_column(db.String(64))
    urgency: Mapped[str] = mapped_column(db.String(16))
    status: Mapped[str] = mapped_column(db.String(16), default='pending', index=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey('appointments.id'), nullable=True, unique=True)
    case: Mapped[Case] = relationship(backref=db.backref('appointment_request', uselist=False, cascade='all, delete-orphan'))
    appointment: Mapped[Appointment | None] = relationship()


def request_json(case):
    ticket = db.session.get(AppointmentRequest, case.id)
    if not ticket:
        item = db.session.scalar(db.select(Appointment).join(AppointmentReferral).where(
            AppointmentReferral.case_id == case.id).order_by(
                sql_case((Appointment.status == 'booked', 0), else_=1), Appointment.id.desc()))
        if not item:
            return None
        result = {'reference': item.reference, 'status': 'confirmed'}
    else:
        result = {'reference': ticket.reference, 'status': ticket.status}
        item = ticket.appointment
    if item:
        local = _local(item.starts_at)
        result.update(appointment_reference=item.reference, appointment_status=item.status,
                      appointment_id=item.id, cancellable=_local(item.starts_at) > _now(),
                      doctor=item.doctor.name, department=item.doctor.specialty,
                      time=f'{local.day:02d}/{local.month:02d}/{local.year + 543} {local:%H:%M}')
    return result


def _request_urgency(case):
    for level in ['emergency', 'urgent', 'soon', 'routine']:
        if level in {case.rule_urgency, case.ai_urgency_suggestion, case.clinician_urgency}:
            return level
    return 'routine'


def _now():
    return datetime.now(timezone.utc)


def _today():
    return _now().astimezone(BANGKOK).date()


def _local(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(BANGKOK)


def _owner():
    if "booking_owner" not in session:
        session["booking_owner"] = secrets.token_urlsafe(32)
    return hashlib.sha256(session["booking_owner"].encode()).hexdigest()


def _day_range(day):
    start = datetime.combine(day, time.min, BANGKOK).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def _parse_day(value):
    try:
        day = date.fromisoformat(value)
    except (ValueError, TypeError):
        abort(400, "Invalid appointment date")
    if not _today() <= day <= _today() + timedelta(days=28):
        abort(400, "Date must be within the next 28 days")
    return day


def _referral_context():
    case = db.session.get(Case, session.get('appointment_case_id')) if session.get('appointment_case_id') else None
    if not case or not hmac.compare_digest(case.token_hash, session.get('appointment_case_hash', '')):
        return None, {'state': 'missing', 'department': None, 'label': 'เริ่มซักประวัติก่อนนัด',
                      'reason': 'ระบบต้องมีข้อมูลอาการเพื่อแนะนำแผนก คุณไม่ต้องเลือกแผนกเอง'}
    return case, recommend_department(case)


@bp.get("/appointments")
def booking():
    owner = _owner()
    bookings = db.session.scalars(db.select(Appointment).where(
        Appointment.owner_hash == owner,
    ).order_by(Appointment.starts_at.desc()).limit(30)).all()
    case, referral = _referral_context()
    ticket = request_json(case) if case else None
    doctors = db.session.scalars(db.select(Doctor).where(Doctor.specialty == referral['label']).order_by(Doctor.id)).all() if referral['state'] == 'ready' and (not ticket or ticket.get('appointment_status') == 'cancelled') else []
    if not doctors:
        return render_template("appointments.html", doctors=[], selected=None, slots=[], bookings=bookings, upcoming={}, referral=referral, case=case, ticket=ticket)
    selected = db.session.get(Doctor, request.args.get("doctor", doctors[0].id))
    if selected is None:
        abort(404)
    if selected.specialty != referral['label']:
        flash('ระบบแสดงเฉพาะแพทย์ในแผนกที่แนะนำสำหรับเคสนี้', 'error')
        return redirect(url_for('appointments.booking'), code=303)
    future = db.session.scalars(db.select(AppointmentSlot).where(
        AppointmentSlot.starts_at > _now(), AppointmentSlot.state == "free",
        AppointmentSlot.starts_at < _day_range(_today() + timedelta(days=29))[0],
    ).order_by(AppointmentSlot.starts_at)).all()
    upcoming = {}
    for slot in future:
        days = upcoming.setdefault(slot.doctor_id, [])
        day = _local(slot.starts_at).date()
        if day not in days and len(days) < 4:
            days.append(day)
    day = _parse_day(request.args["day"]) if request.args.get("day") else next(iter(upcoming.get(selected.id, [])), _today())
    start, end = _day_range(day)
    slots = db.session.scalars(db.select(AppointmentSlot).where(
        AppointmentSlot.doctor_id == selected.id, AppointmentSlot.starts_at >= start,
        AppointmentSlot.starts_at < end, AppointmentSlot.starts_at > _now(),
    ).order_by(AppointmentSlot.starts_at)).all()
    return render_template("appointments.html", doctors=doctors, selected=selected, day=day,
        slots=slots, bookings=bookings, upcoming=upcoming, today=_today(), maximum=_today() + timedelta(days=28), referral=referral, case=case, ticket=ticket)


@bp.post('/appointments/request')
@limiter.limit('8 per minute')
def request_appointment():
    _require_csrf()
    case, referral = _referral_context()
    if not case or request.form.get('case_id') != case.id:
        abort(409, 'Intake case changed; refresh the page')
    receipt = request_json(case)
    if receipt and receipt.get('appointment_status') == 'booked':
        return redirect(url_for('appointments.booking'), code=303)
    existing = db.session.get(AppointmentRequest, case.id)
    if existing and existing.appointment and existing.appointment.status == 'cancelled':
        changed = db.session.execute(update(AppointmentRequest).execution_options(synchronize_session=False).where(
            AppointmentRequest.case_id == case.id, AppointmentRequest.status == 'confirmed',
            AppointmentRequest.appointment_id == existing.appointment_id
        ).values(status='pending', appointment_id=None, owner_hash=_owner(), urgency=_request_urgency(case))).rowcount
        if changed:
            db.session.add(AuditEvent(case=case, actor='patient', action='appointment_requested_again'))
        db.session.commit()
    elif not existing:
        db.session.add(AppointmentRequest(case=case, reference='REQ-' + secrets.token_hex(4).upper(),
            owner_hash=_owner(), urgency=_request_urgency(case), status='pending'))
        db.session.add(AuditEvent(case=case, actor='patient', action='appointment_requested',
                                 detail={'urgency': _request_urgency(case)}))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if not db.session.get(AppointmentRequest, case.id):
                raise
    flash('ส่งคำขอนัดแล้ว ดูสถานะและเวลาที่เจ้าหน้าที่ยืนยันได้ในหน้านี้', 'success')
    return redirect(url_for('appointments.booking'), code=303)


@bp.post("/appointments/book")
@limiter.limit("10 per minute")
def book():
    _require_csrf()
    case, referral = _referral_context()
    if referral['state'] != 'ready':
        abort(409, 'Complete intake and obtain a routine referral before booking')
    if request.form.get('case_id') != case.id:
        abort(409, 'Intake case changed; refresh the booking page')
    ticket = db.session.get(AppointmentRequest, case.id)
    if ticket and ticket.status == 'pending':
        flash('ส่งคำขอให้เจ้าหน้าที่จัดนัดแล้ว ดูผลในหน้ารายละเอียดนัด', 'success')
        return redirect(url_for('appointments.booking'), code=303)
    receipt = request_json(case)
    if receipt and receipt.get('appointment_status') == 'booked':
        flash('เคสนี้มีนัดยืนยันแล้ว ดูเลขนัดและวันเวลาด้านล่าง หากต้องเปลี่ยนเวลาให้ยกเลิกนัดเดิมก่อน', 'success')
        return redirect(url_for('appointments.booking'), code=303)
    slot = db.get_or_404(AppointmentSlot, request.form.get("slot_id", type=int))
    if slot.doctor.specialty != referral['label']:
        abort(409, 'Doctor is outside the recommended department')
    # A unique case request is claimed in the same transaction as the slot.
    # This also prevents double clicks from reserving different slots for one case.
    if ticket:
        claimed_case = db.session.execute(update(AppointmentRequest).execution_options(synchronize_session=False).where(
            AppointmentRequest.case_id == case.id, AppointmentRequest.status == 'confirmed',
            AppointmentRequest.appointment_id == ticket.appointment_id
        ).values(appointment_id=None, owner_hash=_owner())).rowcount
        if claimed_case != 1:
            db.session.rollback()
            flash('สถานะนัดเปลี่ยนแล้ว กรุณาดูรายการนัดล่าสุด', 'error')
            return redirect(url_for('appointments.booking'), code=303)
    else:
        ticket = AppointmentRequest(case_id=case.id, reference='REQ-' + secrets.token_hex(4).upper(),
            owner_hash=_owner(), urgency=_request_urgency(case), status='confirmed')
        db.session.add(ticket)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            flash('เคสนี้กำลังจองหรือมีนัดแล้ว กรุณาดูรายการล่าสุด', 'error')
            return redirect(url_for('appointments.booking'), code=303)
    # Claim the slot in the database, so simultaneous bookings cannot both win.
    claimed = db.session.execute(update(AppointmentSlot).execution_options(synchronize_session=False).where(
        AppointmentSlot.id == slot.id, AppointmentSlot.state == "free",
        AppointmentSlot.starts_at > _now(),
        AppointmentSlot.starts_at < _day_range(_today() + timedelta(days=29))[0],
    ).values(state="booked")).rowcount
    if claimed != 1:
        db.session.rollback()
        flash("คิวนี้ถูกจอง ปิดรับ หรือผ่านเวลาแล้ว กรุณาเลือกคิวใหม่", "error")
        return redirect(url_for("appointments.booking", doctor=slot.doctor_id), code=303)
    appointment = Appointment(reference="APT-" + secrets.token_hex(4).upper(), owner_hash=_owner(),
        slot_id=slot.id, doctor_id=slot.doctor_id, starts_at=slot.starts_at)
    appointment.referral = AppointmentReferral(case_id=case.id, department=referral['department'], reason=referral['reason'][:260])
    db.session.add(appointment)
    try:
        db.session.flush()
        db.session.execute(update(AppointmentRequest).where(AppointmentRequest.case_id == case.id).values(
            status='confirmed', appointment_id=appointment.id))
        db.session.add(AuditEvent(case=case, actor='patient', action='appointment_booked',
            detail={'reference': appointment.reference, 'doctor_id': appointment.doctor_id}))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("จองคิวนี้ไม่สำเร็จ กรุณาเลือกคิวใหม่", "error")
    else:
        flash("จองนัดทดลองสำเร็จ รหัสนัด " + appointment.reference, "success")
    return redirect(url_for("appointments.booking", doctor=slot.doctor_id), code=303)


def _cancel(appointment, owner=None):
    conditions = [Appointment.id == appointment.id, Appointment.status == "booked", Appointment.starts_at > _now()]
    if owner:
        conditions.append(Appointment.owner_hash == owner)
    slot_id = appointment.slot_id
    changed = db.session.execute(update(Appointment).execution_options(synchronize_session=False).where(*conditions).values(status="cancelled", slot_id=None)).rowcount
    if changed and slot_id:
        db.session.execute(update(AppointmentSlot).execution_options(synchronize_session=False).where(AppointmentSlot.id == slot_id, AppointmentSlot.state == "booked").values(state="free"))
    db.session.commit()
    flash("ยกเลิกนัดและคืนคิวแล้ว" if changed else "นัดนี้ยกเลิกไปแล้วหรือผ่านเวลานัดแล้ว", "success" if changed else "error")


@bp.post("/appointments/<int:appointment_id>/cancel")
def cancel(appointment_id):
    _require_csrf()
    appointment = db.get_or_404(Appointment, appointment_id)
    owner = _owner()
    if appointment.owner_hash != owner:
        case, _ = _referral_context()
        ticket = db.session.get(AppointmentRequest, case.id) if case else None
        if not ((ticket and ticket.appointment_id == appointment.id) or
                (case and appointment.referral and appointment.referral.case_id == case.id)):
            abort(404)
        _cancel(appointment)
    else:
        _cancel(appointment, owner)
    return redirect(url_for("appointments.booking"), code=303)


@bp.route("/staff/appointments", methods=["GET", "POST"])
def staff_calendar():
    staff_user = _staff_required()
    day = _parse_day(request.values.get("day", _today().isoformat()))
    doctor_id = request.values.get("doctor", "demo-mint")
    doctor = db.get_or_404(Doctor, doctor_id)
    if request.method == "POST":
        _require_csrf()
        action = request.form.get("action")
        if action == "add":
            try:
                start_time = time.fromisoformat(request.form.get("time", ""))
            except ValueError:
                abort(400)
            if start_time.tzinfo or start_time.second or start_time.microsecond or start_time.minute not in {0, 30} or not 8 <= start_time.hour <= 17:
                abort(400)
            starts_at = datetime.combine(day, start_time, BANGKOK).astimezone(timezone.utc)
            if starts_at <= _now():
                abort(400)
            db.session.add(AppointmentSlot(doctor_id=doctor.id, starts_at=starts_at, state="free"))
            try:
                db.session.commit()
                flash("เพิ่มคิว 30 นาทีแล้ว", "success")
            except IntegrityError:
                db.session.rollback()
                flash("มีคิวเวลานี้อยู่แล้ว", "error")
        elif action in {"block", "open"}:
            slot = db.get_or_404(AppointmentSlot, request.form.get("slot_id", type=int))
            if slot.doctor_id != doctor.id:
                abort(400)
            changed = db.session.execute(update(AppointmentSlot).execution_options(synchronize_session=False).where(AppointmentSlot.id == slot.id,
                AppointmentSlot.state == ("free" if action == "block" else "blocked"),
                AppointmentSlot.starts_at > _now()).values(state="blocked" if action == "block" else "free")).rowcount
            db.session.commit()
            flash("ปรับคิวแล้ว" if changed else "แก้คิวที่ถูกจองหรือผ่านเวลาแล้วไม่ได้ กรุณาจัดการนัดก่อน", "success" if changed else "error")
        elif action == "cancel":
            appointment = db.get_or_404(Appointment, request.form.get("appointment_id", type=int))
            if appointment.doctor_id != doctor.id:
                abort(400)
            _cancel(appointment)
        elif action == 'assign_request':
            ticket = db.get_or_404(AppointmentRequest, request.form.get('case_id', ''))
            slot = db.get_or_404(AppointmentSlot, request.form.get('slot_id', type=int))
            if slot.doctor_id != doctor.id or _local(slot.starts_at).date() != day:
                abort(400)
            if _request_urgency(ticket.case) in {'urgent', 'emergency'} and request.form.get('followup') != 'yes':
                flash('กรุณายืนยันว่าเป็นนัดติดตาม ไม่แทนการดูแลเร่งด่วน', 'error')
                return redirect(url_for('appointments.staff_calendar', doctor=doctor.id, day=day.isoformat()), code=303)
            claimed = db.session.execute(update(AppointmentRequest).execution_options(synchronize_session=False).where(
                AppointmentRequest.case_id == ticket.case_id, AppointmentRequest.status == 'pending'
            ).values(status='confirmed')).rowcount
            reserved = db.session.execute(update(AppointmentSlot).execution_options(synchronize_session=False).where(
                AppointmentSlot.id == slot.id, AppointmentSlot.state == 'free',
                AppointmentSlot.starts_at > _now()
            ).values(state='booked')).rowcount if claimed else 0
            if not claimed or not reserved:
                db.session.rollback()
                flash('คำขอนี้จัดนัดแล้ว หรือคิวนี้ไม่ว่าง กรุณาโหลดหน้าใหม่', 'error')
            else:
                item = Appointment(reference='APT-' + secrets.token_hex(4).upper(), owner_hash=ticket.owner_hash,
                    slot_id=slot.id, doctor_id=doctor.id, starts_at=slot.starts_at)
                item.referral = AppointmentReferral(case_id=ticket.case_id,
                    department=next((k for k, label in DEPARTMENTS.items() if label == doctor.specialty), 'general'),
                    reason='เจ้าหน้าที่จัดนัดจากคำขอ ' + ticket.reference)
                db.session.add(item)
                db.session.flush()
                ticket.appointment_id = item.id
                db.session.add(AuditEvent(case=ticket.case, actor='staff:' + staff_user.username,
                    action='appointment_request_confirmed', detail={'request': ticket.reference,
                    'appointment': item.reference, 'doctor': doctor.id,
                    'followup': request.form.get('followup') == 'yes'}))
                db.session.commit()
                flash('ยืนยันนัด ' + item.reference + ' แล้ว ผู้รับบริการเห็นวันเวลาในหน้าของตน', 'success')
        else:
            abort(400)
        return redirect(url_for("appointments.staff_calendar", doctor=doctor.id, day=day.isoformat()), code=303)
    start, end = _day_range(day)
    slots = db.session.scalars(db.select(AppointmentSlot).where(AppointmentSlot.doctor_id == doctor.id,
        AppointmentSlot.starts_at >= start, AppointmentSlot.starts_at < end).order_by(AppointmentSlot.starts_at)).all()
    appointments = db.session.scalars(db.select(Appointment).where(Appointment.doctor_id == doctor.id,
        Appointment.starts_at >= start, Appointment.starts_at < end).order_by(Appointment.starts_at)).all()
    return render_template("staff_appointments.html", doctors=db.session.scalars(db.select(Doctor).order_by(Doctor.id)).all(),
        selected=doctor, day=day, slots=slots, bookings=appointments, today=_today(), maximum=_today() + timedelta(days=28),
        pending_requests=db.session.scalars(db.select(AppointmentRequest).where(AppointmentRequest.status == 'pending').order_by(
            sql_case((AppointmentRequest.urgency == 'emergency', 0), (AppointmentRequest.urgency == 'urgent', 1), else_=2),
            AppointmentRequest.created_at).limit(100)).all())


def init_app(app):
    app.register_blueprint(bp)
    app.jinja_env.filters["appointment_date"] = lambda value: f"{value.day} {MONTHS[value.month - 1]} {value.year + 543}"
    app.jinja_env.filters["appointment_local"] = _local
    app.jinja_env.filters["appointment_future"] = lambda value: _local(value) > _now()

    @app.cli.command("seed-appointments")
    def seed():
        for doctor_id, name, specialty, weekdays, start_hour, end_hour, label in DEMO_DOCTORS:
            if not db.session.get(Doctor, doctor_id):
                db.session.add(Doctor(id=doctor_id, name=name, specialty=specialty, schedule_label=label))
            db.session.flush()
            existing = set(db.session.scalars(db.select(AppointmentSlot.starts_at).where(AppointmentSlot.doctor_id == doctor_id)))
            existing = {_local(value) for value in existing}
            for offset in range(29):
                day = _today() + timedelta(days=offset)
                if day.weekday() not in weekdays:
                    continue
                for minute in range(start_hour * 60, end_hour * 60, 30):
                    starts_at = datetime.combine(day, time(minute // 60, minute % 60), BANGKOK)
                    if starts_at > _now() and starts_at not in existing:
                        db.session.add(AppointmentSlot(doctor_id=doctor_id, starts_at=starts_at.astimezone(timezone.utc), state="free"))
        db.session.commit()
        click.echo("Demo doctor calendars are ready; existing bookings and closures preserved.")
