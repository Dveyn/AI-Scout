// ---------- Shared UI helpers ----------
function showToast(text) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = text;
  t.classList.add('toast--show');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => t.classList.remove('toast--show'), 2200);
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (_) {}
    document.body.removeChild(ta);
    return true;
  }
}

function copyText(btn) {
  const text = btn.getAttribute('data-copy');
  copyToClipboard(text);
  showToast('Скопировано');
}

// ---------- Lead workspace ----------
function _activeTouch(leadId) {
  return window.__activeTouch?.[leadId] || 1;
}

function switchTouch(leadId, touch) {
  window.__activeTouch = window.__activeTouch || {};
  window.__activeTouch[leadId] = touch;
  document.querySelectorAll(`[id^="touch-${leadId}-"]`).forEach((el) => {
    el.style.display = 'none';
  });
  const panel = document.getElementById(`touch-${leadId}-${touch}`);
  if (panel) panel.style.display = 'block';
  document.querySelectorAll(`.touch-tabs[data-lead="${leadId}"] .touch-tab`).forEach((btn) => {
    btn.classList.toggle('is-active', Number(btn.dataset.touch) === touch);
  });
  const label = document.getElementById(`touch-label-${leadId}`);
  if (label) label.textContent = String(touch);
}

function _msg(leadId, touch) {
  const t = touch ?? _activeTouch(leadId);
  const ta = document.getElementById(`msg-${leadId}-${t}`) || document.getElementById('msg-' + leadId);
  return ta ? ta.value : '';
}
function _subject(leadId, touch) {
  const t = touch ?? _activeTouch(leadId);
  const el = document.getElementById(`subj-${leadId}-${t}`) || document.getElementById('subj-' + leadId);
  return el ? el.value : null;
}

async function saveMessage(leadId, opts = {}) {
  const touch = opts.touch ?? _activeTouch(leadId);
  const body = JSON.stringify({
    subject: _subject(leadId, touch),
    message: _msg(leadId, touch),
    touch,
  });
  const res = await fetch(`/api/leads/${leadId}/message`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body,
  });
  if (!res.ok) {
    showToast('Не удалось сохранить');
    return false;
  }
  if (!opts.silent) {
    const flag = document.getElementById('saved-' + leadId);
    if (flag) { flag.classList.add('is-on'); setTimeout(() => flag.classList.remove('is-on'), 1500); }
    showToast('Сохранено');
  }
  return true;
}

function copyActiveMessage(leadId) {
  copyToClipboard(_msg(leadId));
  showToast('Скопировано');
}

async function openChannel(btn) {
  const leadId = btn.dataset.lead;
  let url = btn.dataset.open;
  const text = _msg(leadId);
  await saveMessage(leadId, { silent: true });
  await copyToClipboard(text);
  if (url.includes('wa.me') && !url.includes('?')) {
    url += '?text=' + encodeURIComponent(text);
  }
  showToast('Текст скопирован — вставьте в чат');
  window.open(url, '_blank');
  _revealMark(leadId);
}

function _revealMark(leadId) {
  const box = document.getElementById('mark-' + leadId);
  if (box) box.style.display = 'flex';
}

async function sendEmail(leadId) {
  const touch = _activeTouch(leadId);
  const ok = await saveMessage(leadId, { silent: true, touch });
  if (!ok) return;
  showToast('Отправляем email…');
  const res = await fetch(`/api/leads/${leadId}/send?touch=${touch}`, { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { showToast('Ошибка отправки'); return; }
  if (data.send_status === 'sent') {
    showToast(`Касание ${touch} отправлено ✓`);
  } else {
    showToast('Статус: ' + (data.send_status || 'нет email'));
  }
  setTimeout(() => location.reload(), 700);
}

async function markSent(leadId, channel) {
  const touch = _activeTouch(leadId);
  const res = await fetch(
    `/api/leads/${leadId}/mark-sent?channel=${encodeURIComponent(channel || 'manual')}&touch=${touch}`,
    { method: 'POST' }
  );
  if (!res.ok) { showToast('Ошибка'); return; }
  showToast('Отмечено как отправленное ✓');
  setTimeout(() => location.reload(), 500);
}

async function sendAll(jobId, touch = 1) {
  const label = touch === 1 ? 'первое касание' : `касание ${touch}`;
  if (!confirm(`Отправить email (${label}) всем target с адресом?`)) return;
  showToast('Рассылаем email…');
  const res = await fetch(`/api/jobs/${jobId}/send?touch=${touch}`, { method: 'POST' });
  if (!res.ok) { showToast('Ошибка'); return; }
  setTimeout(() => location.reload(), 700);
}

// ---------- Filtering ----------
function filterLeads(type, btn) {
  document.querySelectorAll('.filter').forEach((f) => f.classList.remove('is-active'));
  if (btn) btn.classList.add('is-active');
  document.querySelectorAll('.lead').forEach((lead) => {
    let show = true;
    if (type === 'target') show = lead.dataset.target === '1';
    else if (type === 'ready') show = lead.dataset.target === '1' && lead.dataset.contact === '1' && lead.dataset.status !== 'sent';
    else if (type === 'sent') show = lead.dataset.status === 'sent';
    else if (type === 'nocontact') show = lead.dataset.target === '1' && lead.dataset.contact === '0';
    lead.style.display = show ? '' : 'none';
  });
}
