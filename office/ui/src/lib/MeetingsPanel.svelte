<script>
  import { onMount } from 'svelte';
  import { listMeetings, startStandup } from './api.js';

  let { onchange, ontoast } = $props();

  let meetings = $state([]);
  let agenda = $state('Ежедневный standup: KPI, план, блокеры');
  let lastResult = $state(null);
  let busy = $state(false);

  async function load() {
    const data = await listMeetings();
    meetings = data.meetings ?? [];
  }

  onMount(load);

  async function standup() {
    busy = true;
    try {
      lastResult = await startStandup(agenda);
      ontoast?.('Standup завершён');
      onchange?.();
      await load();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }
</script>

<div class="card">
  <h2>Запустить standup</h2>
  <p style="color:var(--muted);font-size:0.85rem;margin-bottom:0.75rem">
    Совещание руководителей отделов → синтез COO → план дня. При недоступности GPTunnel — локальный отчёт по KPI.
  </p>
  <div class="form-row">
    <label>Повестка</label>
    <textarea bind:value={agenda}></textarea>
  </div>
  <button onclick={standup} disabled={busy}>{busy ? 'Идёт совещание…' : 'Начать standup'}</button>
</div>

{#if lastResult}
  <div class="card">
    <h2>Итог COO</h2>
    {#if lastResult.mode === 'local'}
      <p class="badge blocked" style="display:inline-block;margin-bottom:0.5rem">Локальный режим (без GPTunnel)</p>
    {/if}
    <p>{lastResult.coo_synthesis}</p>
    {#if lastResult.items?.length}
      <h3 style="margin-top:0.75rem;font-size:0.9rem">Отчёты отделов</h3>
      <ul class="list">
        {#each lastResult.items as item}
          <li>
            <strong>{item.department_slug}</strong>: {item.report?.slice?.(0, 200)}
          </li>
        {/each}
      </ul>
    {/if}
    {#if lastResult.day_plan?.length}
      <h3 style="margin-top:0.75rem;font-size:0.9rem">План дня</h3>
      <ul class="list">
        {#each lastResult.day_plan as item}
          <li>{item}</li>
        {/each}
      </ul>
    {/if}
    <p style="color:var(--muted);font-size:0.8rem;margin-top:0.5rem">
      Расход: {lastResult.cost_rub?.toFixed?.(2) ?? 0} ₽
    </p>
  </div>
{/if}

<div class="card">
  <h2>История совещаний</h2>
  <ul class="list">
    {#each meetings as m}
      <li>
        <strong>{m.title}</strong> — {m.status}
        <div style="color:var(--muted);font-size:0.8rem">{m.transcript_summary?.slice?.(0, 120)}</div>
      </li>
    {:else}
      <li style="color:var(--muted)">Совещаний пока нет</li>
    {/each}
  </ul>
</div>
