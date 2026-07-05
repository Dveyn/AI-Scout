<script>
  import { onMount } from 'svelte';
  import { fetchEvents, scanEvents, updateEventStatus } from './api.js';

  let { onchange, ontoast } = $props();

  let events = $state([]);
  let busy = $state(false);
  let filter = $state('all');
  let brief = $state(
    'Собери онлайн-мероприятия (вебинары, мастер-классы), где будут владельцы и директора B2B SMB — потенциальные клиенты веб-студии'
  );

  const typeLabels = {
    webinar: 'Вебинар',
    masterclass: 'Мастер-класс',
    conference: 'Конференция',
    forum: 'Форум',
    other: 'Другое',
  };

  const statusLabels = {
    new: 'Новое',
    reviewed: 'Просмотрено',
    registered: 'Записался',
    skipped: 'Пропуск',
  };

  async function load() {
    const status = filter === 'all' ? null : filter;
    const data = await fetchEvents(status);
    events = data.events ?? [];
  }

  onMount(load);

  async function scan() {
    busy = true;
    try {
      const res = await scanEvents(brief);
      ontoast?.(res.summary ?? res.error ?? 'Сканирование завершено');
      onchange?.();
      await load();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }

  async function setStatus(id, status) {
    try {
      await updateEventStatus(id, status);
      await load();
    } catch (e) {
      ontoast?.(e.message);
    }
  }
</script>

<div class="card">
  <h2>Мониторинг мероприятий</h2>
  <p style="color:var(--muted);font-size:0.85rem;margin-bottom:0.75rem">
    Секретарь ищет вебинары и мастер-классы, где собирается ваша B2B-аудитория. Результаты сохраняются в базу office.
  </p>
  <div class="form-row">
    <label for="events-brief">Задача для сбора</label>
    <textarea id="events-brief" bind:value={brief}></textarea>
  </div>
  <button onclick={scan} disabled={busy}>
    {busy ? 'Секретарь ищет…' : '🔍 Запустить сбор мероприятий'}
  </button>
  <p style="color:var(--muted);font-size:0.8rem;margin-top:0.5rem">
    Или кликните на стол секретаря в офисе и дайте задачу со словами «собери мероприятия».
  </p>
</div>

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap">
    <h2>Найденные мероприятия ({events.length})</h2>
    <select bind:value={filter} onchange={load}>
      <option value="all">Все</option>
      <option value="new">Новые</option>
      <option value="reviewed">Просмотренные</option>
      <option value="registered">Записался</option>
      <option value="skipped">Пропущенные</option>
    </select>
  </div>

  <ul class="list event-list">
    {#each events as ev (ev.id)}
      <li class="event-item">
        <div class="event-head">
          <strong>
            <a href={ev.url} target="_blank" rel="noopener noreferrer">{ev.title}</a>
          </strong>
          <span class="badge {ev.status}">{statusLabels[ev.status] ?? ev.status}</span>
        </div>
        <div class="event-meta">
          {typeLabels[ev.event_type] ?? ev.event_type}
          {#if ev.date_hint} · {ev.date_hint}{/if}
          · релевантность {ev.relevance}/10
        </div>
        {#if ev.audience}
          <p class="event-audience">Аудитория: {ev.audience}</p>
        {/if}
        {#if ev.why_relevant}
          <p class="event-why">{ev.why_relevant}</p>
        {/if}
        {#if ev.registration_hint}
          <p class="event-reg">Запись: {ev.registration_hint}</p>
        {/if}
        <div class="event-actions">
          <button class="ghost" onclick={() => setStatus(ev.id, 'reviewed')}>✓ Просмотрено</button>
          <button class="ghost" onclick={() => setStatus(ev.id, 'registered')}>📅 Записался</button>
          <button class="ghost" onclick={() => setStatus(ev.id, 'skipped')}>✕ Пропуск</button>
        </div>
      </li>
    {:else}
      <li style="color:var(--muted)">Пока пусто — запустите сбор или дайте задачу секретарю</li>
    {/each}
  </ul>
</div>

<style>
  .event-list { margin-top: 0.75rem; }
  .event-item {
    padding: 0.85rem 0;
    border-bottom: 1px solid var(--border);
  }
  .event-head {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    align-items: flex-start;
  }
  .event-meta {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 0.25rem;
  }
  .event-audience, .event-why, .event-reg {
    font-size: 0.85rem;
    margin-top: 0.35rem;
    color: var(--text);
  }
  .event-actions {
    display: flex;
    gap: 0.35rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
  }
  .badge.new { background: #2a3d5c; }
  .badge.reviewed { background: #3d3d2a; }
  .badge.registered { background: #1e3d2a; }
  .badge.skipped { background: #3d1e1e; }
</style>
