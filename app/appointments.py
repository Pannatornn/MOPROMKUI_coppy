"""Anonymous demo appointments with independent doctor calendars."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import secrets

import click
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import ForeignKey, UniqueConstraint, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db, limiter
from .routes import _require_csrf, _staff_required

BANGKOK = timezone(timedelta(hours=7))
bp = Blueprint("appointments", __name__)
MONTHS = "มกราคม กุมภาพันธ์ มีนาคม เมษายน พฤษภาคม มิถุนายน กรกฎาคม สิงหาคม กันยายน ตุลาคม พฤศจิกายน ธันวาคม".split()
DEMO_DOCTORS = [
    ("demo-mint", "พญ.มินตรา", "เวชปฏิบัติทั่วไป", {0, 2, 4}, 9, 12, "จันทร์ · พุธ · ศุกร์ 09:00–12:00"),
    ("demo-nont", "นพ.นนทกร", "อายุรกรรม", {1, 3}, 13, 16, "อังคาร · พฤหัสบดี 13:00–16:00"),
    ("demo-pim", "พญ.พิมพ์ชนก", "ผิวหนัง", {2, 5}, 10, 14, "พุธ · เสาร์ 10:00–14:00"),
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


@bp.get("/appointments")
def booking():
    owner = _owner()
    doctors = db.session.scalars(db.select(Doctor).order_by(Doctor.id)).all()
    if not doctors:
        return render_template("appointments.html", doctors=[], selected=None, slots=[], bookings=[], upcoming={})
    selected = db.session.get(Doctor, request.args.get("doctor", doctors[0].id))
    if selected is None:
        abort(404)
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
    bookings = db.session.scalars(db.select(Appointment).where(
        Appointment.owner_hash == owner,
    ).order_by(Appointment.starts_at.desc()).limit(30)).all()
    return render_template("appointments.html", doctors=doctors, selected=selected, day=day,
        slots=slots, bookings=bookings, upcoming=upcoming, today=_today(), maximum=_today() + timedelta(days=28))


@bp.post("/appointments/book")
@limiter.limit("10 per minute")
def book():
    _require_csrf()
    slot = db.get_or_404(AppointmentSlot, request.form.get("slot_id", type=int))
    # Claim the slot in the database, so simultaneous bookings cannot both win.
    claimed = db.session.execute(update(AppointmentSlot).where(
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
    db.session.add(appointment)
    try:
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
    changed = db.session.execute(update(Appointment).where(*conditions).values(status="cancelled", slot_id=None)).rowcount
    if changed and slot_id:
        db.session.execute(update(AppointmentSlot).where(AppointmentSlot.id == slot_id, AppointmentSlot.state == "booked").values(state="free"))
    db.session.commit()
    flash("ยกเลิกนัดและคืนคิวแล้ว" if changed else "นัดนี้ยกเลิกไปแล้วหรือผ่านเวลานัดแล้ว", "success" if changed else "error")


@bp.post("/appointments/<int:appointment_id>/cancel")
def cancel(appointment_id):
    _require_csrf()
    appointment = db.get_or_404(Appointment, appointment_id)
    if appointment.owner_hash != _owner():
        abort(404)
    _cancel(appointment, _owner())
    return redirect(url_for("appointments.booking"), code=303)


@bp.route("/staff/appointments", methods=["GET", "POST"])
def staff_calendar():
    _staff_required()
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
            changed = db.session.execute(update(AppointmentSlot).where(AppointmentSlot.id == slot.id,
                AppointmentSlot.state == ("free" if action == "block" else "blocked"),
                AppointmentSlot.starts_at > _now()).values(state="blocked" if action == "block" else "free")).rowcount
            db.session.commit()
            flash("ปรับคิวแล้ว" if changed else "แก้คิวที่ถูกจองหรือผ่านเวลาแล้วไม่ได้ กรุณาจัดการนัดก่อน", "success" if changed else "error")
        elif action == "cancel":
            appointment = db.get_or_404(Appointment, request.form.get("appointment_id", type=int))
            if appointment.doctor_id != doctor.id:
                abort(400)
            _cancel(appointment)
        else:
            abort(400)
        return redirect(url_for("appointments.staff_calendar", doctor=doctor.id, day=day.isoformat()), code=303)
    start, end = _day_range(day)
    slots = db.session.scalars(db.select(AppointmentSlot).where(AppointmentSlot.doctor_id == doctor.id,
        AppointmentSlot.starts_at >= start, AppointmentSlot.starts_at < end).order_by(AppointmentSlot.starts_at)).all()
    appointments = db.session.scalars(db.select(Appointment).where(Appointment.doctor_id == doctor.id,
        Appointment.starts_at >= start, Appointment.starts_at < end).order_by(Appointment.starts_at)).all()
    return render_template("staff_appointments.html", doctors=db.session.scalars(db.select(Doctor).order_by(Doctor.id)).all(),
        selected=doctor, day=day, slots=slots, bookings=appointments, today=_today(), maximum=_today() + timedelta(days=28))


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
