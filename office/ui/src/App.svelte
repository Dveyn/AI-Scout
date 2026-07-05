<script>
  import ChiefPanel from './lib/ChiefPanel.svelte';
  import OfficeFloor from './lib/OfficeFloor.svelte';
  import GoalsPanel from './lib/GoalsPanel.svelte';
  import WorkstationsPanel from './lib/WorkstationsPanel.svelte';
  import MeetingsPanel from './lib/MeetingsPanel.svelte';
  import EventsPanel from './lib/EventsPanel.svelte';
  import BudgetPanel from './lib/BudgetPanel.svelte';
  import { fetchOverview, connectEvents } from './lib/api.js';
  import { onMount } from 'svelte';
  import './lib/office-floor.css';

  let tab = $state('floor');
  let overview = $state(null);
  let toast = $state('');
  let loading = $state(true);

  const tabs = [
    { id: 'chief', label: '👔 Задача' },
    { id: 'floor', label: '🏢 Офис' },
    { id: 'events', label: '📅 Мероприятия' },
    { id: 'goals', label: '🎯 Цели' },
    { id: 'meetings', label: '🪑 Совещания' },
    { id: 'budget', label: '💰 Бюджет' },
    { id: 'desks', label: '⚙️ Настройки' },
  ];

  async function refresh() {
    loading = true;
    try {
      overview = await fetchOverview();
    } catch (e) {
      toast = 'Ошибка загрузки: ' + e.message;
    } finally {
      loading = false;
    }
  }

  function showToast(msg) {
    toast = msg;
    setTimeout(() => (toast = ''), 4000);
  }

  onMount(() => {
    refresh();
    const es = connectEvents((ev) => {
      if (ev.type !== 'ping' && ev.type !== 'connected') {
        showToast(ev.type);
        refresh();
      }
    });
    return () => es.close();
  });
</script>

<div class="layout">
  <aside class="sidebar">
    <h1>AI Office</h1>
    <p class="sub">CEO-кабинет · ВебШтрих</p>
    <a class="scout-link" href="http://localhost:8080/department" target="_blank" rel="noopener">→ Scout / Маркетинг</a>
    <nav class="nav">
      {#each tabs as t}
        <button class:active={tab === t.id} onclick={() => (tab = t.id)}>{t.label}</button>
      {/each}
    </nav>
    <button class="ghost" style="margin-top:1rem;width:100%" onclick={refresh} disabled={loading}>
      {loading ? 'Загрузка…' : 'Обновить'}
    </button>
  </aside>

  <main class="main">
    {#if overview}
      <div class="stats">
        <div class="stat">
          <div class="val">{overview.workstations?.length ?? 0}</div>
          <div class="lbl">Сотрудников</div>
        </div>
        <div class="stat">
          <div class="val">{overview.goals?.length ?? 0}</div>
          <div class="lbl">Целей</div>
        </div>
        <div class="stat">
          <div class="val">{overview.scout_stats?.targets ?? 0}</div>
          <div class="lbl">Лиды Scout</div>
        </div>
        <div class="stat">
          <div class="val">{overview.budget_global?.spent_rub?.toFixed?.(1) ?? 0} ₽</div>
          <div class="lbl">Расход office</div>
        </div>
      </div>
    {/if}

    {#if tab === 'chief'}
      <ChiefPanel onchange={refresh} ontoast={showToast} />
    {:else if tab === 'floor'}
      {#if overview}
        <OfficeFloor {overview} onchange={refresh} ontoast={showToast} />
      {:else}
        <p class="muted">Загрузка офиса…</p>
      {/if}
    {:else if tab === 'desks'}
      <h2 class="page-title">Настройки рабочих мест</h2>
      <WorkstationsPanel {overview} onchange={refresh} ontoast={showToast} />
    {:else if tab === 'events'}
      <h2 class="page-title">Онлайн-мероприятия</h2>
      <EventsPanel onchange={refresh} ontoast={showToast} />
    {:else if tab === 'goals'}
      <h2 class="page-title">Цели</h2>
      <GoalsPanel {overview} onchange={refresh} ontoast={showToast} />
    {:else if tab === 'meetings'}
      <h2 class="page-title">Совещания</h2>
      <MeetingsPanel onchange={refresh} ontoast={showToast} />
    {:else if tab === 'budget'}
      <h2 class="page-title">Бюджет токенов</h2>
      <BudgetPanel />
    {/if}
  </main>
</div>

{#if toast}
  <div class="toast">{toast}</div>
{/if}
