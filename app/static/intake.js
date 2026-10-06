(() => {
  const setupPanel = document.querySelector("#setup-panel");
  const chatPanel = document.querySelector("#chat-panel");
  const intakeForm = document.querySelector("#intake-form");
  const messageForm = document.querySelector("#message-form");
  const messageInput = document.querySelector("#message-input");
  const newCaseButton = document.querySelector("#new-case-button");
  const typingIndicator = document.querySelector("#typing-indicator");
  const aiMode = document.querySelector("#ai-mode");
  if (!intakeForm || !messageForm || !messageInput || !aiMode) return;

  let caseId = null;
  let caseToken = null;

  const setStep = (currentStep) => {
    for (const item of document.querySelectorAll("#intake-steps [data-step]")) {
      const step = Number(item.dataset.step);
      item.classList.toggle("active", step === currentStep);
      item.classList.toggle("complete", step < currentStep);
      if (step === currentStep) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
      const marker = item.querySelector("i");
      if (marker) marker.textContent = step < currentStep ? "✓" : String(step);
    }
  };

  const setError = (selector, message) => {
    const element = document.querySelector(selector);
    element.textContent = message || "";
    element.hidden = !message;
  };

  const setBusy = (form, busy, busyLabel = "กำลังส่งข้อมูล...") => {
    form.classList.toggle("is-busy", busy);
    const button = form.querySelector('[type="submit"]');
    if (!button) return;
    if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
    button.disabled = busy;
    button.innerHTML = busy ? busyLabel : button.dataset.originalHtml;
  };

  const appendMessage = (role, content) => {
    const wrap = document.createElement("article");
    wrap.className = `message message-${role}`;
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.textContent = role === "patient" ? "คุณ" : "AI";
    const bubble = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = role === "patient" ? "คำตอบของคุณ" : "หมอพร้อมคุย";
    const text = document.createElement("p");
    text.textContent = content;
    bubble.append(label, text);
    wrap.append(avatar, bubble);
    document.querySelector("#messages").appendChild(wrap);
    wrap.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  const renderCase = (data, reset = false) => {
    if (reset) {
      document.querySelector("#messages").replaceChildren();
      for (const message of data.messages || []) appendMessage(message.role, message.content);
    }
    document.querySelector("#case-reference").textContent = data.reference;
    const patientTurns = (data.messages || []).filter((item) => item.role === "patient").length;
    document.querySelector("#question-progress").textContent = `ตอบแล้ว ${patientTurns} ข้อ`;
    document.querySelector("#progress-fill").style.width = `${Math.min(100, Math.max(10, patientTurns / 8 * 100))}%`;

    if (data.ai_mode === "ai") {
      aiMode.className = "ai-mode ai-mode-online";
      aiMode.textContent = `${data.ai_provider === "gemini" ? "Gemini AI" : "AI"} วิเคราะห์ทุกข้อความ`;
    } else if (data.ai_mode === "safety_rule") {
      aiMode.className = "ai-mode ai-mode-rule";
      aiMode.textContent = "กฎฉุกเฉินทำงานก่อน AI";
    } else if (data.ai_mode === "fallback") {
      aiMode.className = "ai-mode ai-mode-fallback";
      aiMode.textContent = "โหมดคำถามสำรอง · AI ไม่พร้อม";
    } else {
      aiMode.className = "ai-mode";
      aiMode.textContent = "กำลังเชื่อมต่อ AI";
    }

    const status = document.querySelector("#case-status");
    const closedForPatient = data.urgency === "emergency" || ["ready", "escalated", "closed"].includes(data.status);
    const urgentReview = data.urgency === "urgent";
    setStep(closedForPatient ? 3 : 2);
    status.hidden = false;
    if (data.urgency === "emergency") {
      status.className = "case-status status-emergency";
      status.innerHTML = "<strong>พบสัญญาณที่อาจฉุกเฉิน</strong><span>หยุดตอบและโทร 1669 ทันที</span>";
    } else if (urgentReview || data.status === "escalated") {
      status.className = "case-status status-urgent";
      status.innerHTML = "<strong>พบอาการที่ควรตรวจโดยเร็ว</strong><span>ระบบแจ้งบุคลากรแล้ว โปรดตอบคำถามต่อ และโทร 1669 หากอาการรุนแรงขึ้นหรือไม่ปลอดภัย</span>";
    } else if (closedForPatient) {
      status.className = "case-status status-ready";
      status.innerHTML = "<strong>ส่งข้อมูลเรียบร้อยแล้ว</strong><span>ข้อมูลพร้อมให้บุคลากรตรวจ คุณสามารถเริ่มเคสใหม่ได้</span>";
    } else {
      status.className = "case-status status-collecting";
      status.innerHTML = "<strong>กำลังซักประวัติ</strong><span>ระบบกำลังรวบรวมข้อมูลเพื่อจัดทำสรุปให้บุคลากรตรวจ</span>";
    }
    messageForm.hidden = closedForPatient;
    const referral = data.appointment_referral;
    const referralPanel = document.querySelector('#appointment-referral');
    referralPanel.hidden = !referral || referral.state !== 'ready';
    if (!referralPanel.hidden) {
      document.querySelector('#referral-label').textContent = referral.label;
      document.querySelector('#referral-reason').textContent = referral.reason;
    }
  };

  const api = async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(caseToken ? { "X-Case-Token": caseToken } : {}),
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({ error: "เซิร์ฟเวอร์ตอบกลับไม่สมบูรณ์" }));
    if (!response.ok && response.status !== 409) throw new Error(data.error || "เกิดข้อผิดพลาด กรุณาลองใหม่");
    return data;
  };

  const clearActiveCase = () => {
    sessionStorage.removeItem("mpk_case_id");
    sessionStorage.removeItem("mpk_case_token");
    caseId = null;
    caseToken = null;
    intakeForm.reset();
    messageForm.reset();
    document.querySelector("#messages").replaceChildren();
    document.querySelector("#case-status").hidden = true;
    document.querySelector('#appointment-referral').hidden = true;
    setError("#setup-error", "");
    setError("#chat-error", "");
    chatPanel.hidden = true;
    setupPanel.hidden = false;
    setStep(1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  newCaseButton?.addEventListener("click", () => {
    if (!caseId || window.confirm("เริ่มเคสใหม่ใช่หรือไม่? เคสเดิมยังคงอยู่ในแดชบอร์ดเจ้าหน้าที่")) clearActiveCase();
  });

  intakeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("#setup-error", "");
    const form = new FormData(intakeForm);
    setBusy(intakeForm, true, "กำลังเตรียมคำถามแรก...");
    try {
      const data = await api("/api/cases", {
        method: "POST",
        body: JSON.stringify({
          age_group: form.get("age_group"),
          sex_at_birth: form.get("sex_at_birth"),
          pregnancy_status: form.get("pregnancy_status"),
          chief_complaint: form.get("chief_complaint"),
          consent: form.get("consent") === "on",
        }),
      });
      caseId = data.id;
      caseToken = data.token;
      sessionStorage.setItem("mpk_case_id", caseId);
      sessionStorage.setItem("mpk_case_token", caseToken);
      setupPanel.hidden = true;
      chatPanel.hidden = false;
      renderCase(data, true);
    } catch (error) {
      setError("#setup-error", error.message);
    } finally {
      setBusy(intakeForm, false);
    }
  });

  messageForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("#chat-error", "");
    const content = messageInput.value.trim();
    if (!content) return;
    appendMessage("patient", content);
    messageInput.value = "";
    typingIndicator.hidden = false;
    setBusy(messageForm, true, "กำลังส่ง");
    try {
      const data = await api(`/api/cases/${caseId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      const last = data.messages[data.messages.length - 1];
      if (last && last.role === "assistant") appendMessage("assistant", last.content);
      renderCase(data, false);
    } catch (error) {
      setError("#chat-error", error.message);
    } finally {
      typingIndicator.hidden = true;
      setBusy(messageForm, false);
      messageInput.focus();
    }
  });

  messageInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (messageForm.hidden || messageForm.classList.contains("is-busy")) return;
    if (messageInput.value.trim()) messageForm.requestSubmit();
  });

  const resume = async () => {
    caseId = sessionStorage.getItem("mpk_case_id");
    caseToken = sessionStorage.getItem("mpk_case_token");
    if (!caseId || !caseToken) return;
    try {
      const data = await api(`/api/cases/${caseId}`);
      setupPanel.hidden = true;
      chatPanel.hidden = false;
      renderCase(data, true);
    } catch (_error) {
      clearActiveCase();
    }
  };

  resume();
})();
