from pathlib import Path


def test_intake_reads_form_before_disabling_controls():
    script = (Path(__file__).parents[1] / "app" / "static" / "intake.js").read_text(encoding="utf-8")

    capture = script.index("const form = new FormData(intakeForm);")
    disable = script.index("setBusy(intakeForm, true,", capture)

    assert capture < disable


def test_intake_can_clear_active_case_and_start_again():
    script = (Path(__file__).parents[1] / "app" / "static" / "intake.js").read_text(encoding="utf-8")

    assert 'sessionStorage.removeItem("mpk_case_id")' in script
    assert 'sessionStorage.removeItem("mpk_case_token")' in script
    assert 'newCaseButton?.addEventListener("click"' in script


def test_intake_stepper_advances_with_case_state():
    script = (Path(__file__).parents[1] / "app" / "static" / "intake.js").read_text(encoding="utf-8")

    assert "const setStep = (currentStep)" in script
    assert "setStep(closedForPatient ? 3 : 2);" in script
    assert "setStep(1);" in script


def test_intake_status_is_always_visible_and_enter_submits():
    root = Path(__file__).parents[1]
    template = (root / "app" / "templates" / "intake.html").read_text(encoding="utf-8")
    script = (root / "app" / "static" / "intake.js").read_text(encoding="utf-8")

    assert "status-collecting" in template
    assert "Enter เพื่อส่ง" in template
    assert "status.hidden = false" in script
    assert 'event.key !== "Enter"' in script
    assert "event.shiftKey" in script
    assert "event.isComposing" in script
    assert "messageForm.requestSubmit()" in script


def test_no_demo_banner_and_anakotmai_is_used():
    root = Path(__file__).parents[1]
    base = (root / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    styles = (root / "app" / "static" / "app.css").read_text(encoding="utf-8")

    assert "HACKATHON DEMO" not in base
    assert "demo-ribbon" not in styles
    assert "Anakotmai.css" in base
    assert 'font-family: "Anakotmai"' in styles


def test_ai_mode_is_visible_and_stepper_updates_accessibly():
    root = Path(__file__).parents[1]
    template = (root / "app" / "templates" / "intake.html").read_text(encoding="utf-8")
    script = (root / "app" / "static" / "intake.js").read_text(encoding="utf-8")

    assert 'id="ai-mode"' in template
    assert "วิเคราะห์ทุกข้อความ" in script
    assert "โหมดคำถามสำรอง" in script
    assert 'setAttribute("aria-current", "step")' in script
