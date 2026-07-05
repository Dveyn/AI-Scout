const API = '';

async function fetchJson(url, options = {}, timeoutMs = 120000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${API}${url}`, { ...options, signal: ctrl.signal });
    const text = await r.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    if (!r.ok) {
      const detail = data?.detail ?? text ?? r.statusText;
      if (r.status === 0 || detail === 'Failed to fetch') {
        throw new Error(
          'Сервер office не отвечает. Запустите: make office-dev (порт 8090)'
        );
      }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error('Таймаут — совещание или задача заняли слишком много времени. Попробуйте снова.');
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchOverview() {
  return fetchJson('/api/office/overview', {}, 30000);
}

export async function fetchRegistry() {
  return fetchJson('/api/office/registry');
}

export async function fetchBudget() {
  return fetchJson('/api/office/budget');
}

export async function fetchActivity(workstationId) {
  return fetchJson(`/api/workstations/${workstationId}/activity`);
}

export async function createGoal(horizon, text) {
  return fetchJson('/api/goals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ horizon, text }),
  });
}

export async function cascadeGoal(goalId) {
  return fetchJson(`/api/goals/${goalId}/cascade`, { method: 'POST' }, 120000);
}

export async function createWorkstation(preset_id, name, custom_prompt) {
  return fetchJson('/api/workstations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preset_id, name, custom_prompt }),
  });
}

export async function runWorkstation(id, brief) {
  return fetchJson(
    `/api/workstations/${id}/run`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief }),
    },
    180000
  );
}

export async function startStandup(agenda = '') {
  return fetchJson(
    '/api/meetings/standup',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agenda }),
    },
    300000
  );
}

export async function listMeetings() {
  return fetchJson('/api/meetings');
}

export async function fetchDirectiveMode() {
  return fetchJson('/api/directives/mode');
}

export async function ingestDirectives() {
  return fetchJson('/api/directives/ingest', { method: 'POST' }, 60000);
}

export async function createDirective(brief) {
  return fetchJson(
    '/api/directives',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief }),
    },
    600000
  );
}

export async function fetchDirectives() {
  return fetchJson('/api/directives');
}

export async function fetchEvents(status = null) {
  const q = status ? `?status=${encodeURIComponent(status)}` : '';
  return fetchJson(`/api/online-events${q}`);
}

export async function scanEvents(brief) {
  return fetchJson(
    '/api/online-events/scan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief }),
    },
    300000
  );
}

export async function updateEventStatus(eventId, status) {
  return fetchJson(`/api/online-events/${eventId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
}

export function connectEvents(onEvent) {
  const es = new EventSource(`${API}/api/events`);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {}
  };
  return es;
}
