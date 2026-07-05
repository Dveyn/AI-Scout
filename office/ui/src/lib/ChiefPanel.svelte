<script>
  import { onMount } from 'svelte';
  import { createDirective, fetchDirectiveMode, fetchDirectives, ingestDirectives } from './api.js';

  let { onchange, ontoast } = $props();

  let brief = $state('');
  let busy = $state(false);
  let polling = $state(false);
  let directives = $state([]);
  let lastReport = $state(null);
  let mode = $state({ mode: 'local', hint: '' });

  async function load() {
    const [list, m] = await Promise.all([fetchDirectives(), fetchDirectiveMode()]);
    directives = list.directives ?? [];
    mode = m;
  }

  onMount(load);

  async function pollResult(directiveId, attempts = 45) {
    polling = true;
    for (let i = 0; i < attempts; i++) {
      await ingestDirectives();
      const list = await fetchDirectives();
      directives = list.directives ?? [];
      const d = directives.find((x) => x.id === directiveId);
      if (d?.status === 'completed' && d.final_report) {
        lastReport = d;
        polling = false;
        ontoast?.('Готово');
        onchange?.();
        return;
      }
      await new Promise((r) => setTimeout(r, 8000));
    }
    polling = false;
    ontoast?.('Cursor ещё работает — нажмите «Проверить результат» позже');
  }

  async function checkResults() {
    busy = true;
    try {
      await ingestDirectives();
      await load();
      const waiting = directives.find((d) => d.status === 'completed' && d.final_report);
      if (waiting) lastReport = waiting;
      ontoast?.('Обновлено');
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }

  async function submit() {
    if (!brief.trim()) return;
    busy = true;
    lastReport = null;
    try {
      const res = await createDirective(brief.trim());
      const d = res.directive;
      brief = '';
      await load();
      if (d.status === 'completed' && d.final_report) {
        lastReport = d;
        ontoast?.('Готово');
        onchange?.();
      } else if (d.status === 'waiting_cursor') {
        ontoast?.('Задача в Cursor — ждём результат…');
        pollResult(d.id);
      } else {
        lastReport = d;
        ontoast?.('Задача принята');
        onchange?.();
      }
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }

  function deptLabel(dep) {
    const m = {
      marketing: 'Маркетинг',
      sales: 'Продажи',
      leadgen: 'Лидоген',
      production: 'Продакшн',
    };
    return m[dep] ?? dep;
  }
</script>

<div class="card chief-card">
  <h2>Одна задача → готовый результат</h2>
  {#if mode.mode === 'cursor'}
    <p class="chief-hint">
      Режим <strong>Cursor</strong>: задача уходит в Cursor Automation (ваша подписка, не GPTunnel).
      COO раздаёт отделам, они делают, вы получаете итог здесь.
    </p>
  {:else}
    <p class="chief-hint">Режим <strong>локальный</strong> (GPTunnel). Для Cursor: <code>OFFICE_LLM_PROVIDER=cursor</code> в scout/.env</p>
  {/if}

  <div class="form-row">
    <label for="chief-brief">Что нужно сделать</label>
    <textarea
      id="chief-brief"
      bind:value={brief}
      placeholder="Например: за 2 недели найти 3 клиента на B2B-портал"
      rows="4"
    ></textarea>
  </div>
  <div class="btn-row">
    <button onclick={submit} disabled={busy || polling || !brief.trim()}>
      {#if polling}
        Cursor работает…
      {:else if busy}
        Отправляю…
      {:else}
        Отдать начальнику
      {/if}
    </button>
    {#if mode.mode === 'cursor'}
      <button class="ghost" onclick={checkResults} disabled={busy}>Проверить результат</button>
    {/if}
  </div>

  {#if mode.mode === 'cursor'}
    <p class="cmd-hint">
      Или из терминала:<br />
      <code>make office-task BRIEF="ваша задача"</code><br />
      <code>make office-ingest</code>
    </p>
  {/if}
</div>

{#if lastReport?.final_report}
  <div class="card deliverable-card">
    <h2>✅ Готовый результат</h2>
    <pre class="report-pre">{lastReport.final_report}</pre>
  </div>
{:else if lastReport?.status === 'waiting_cursor'}
  <div class="card">
    <p>⏳ Задача в Cursor. {lastReport.coo_plan}</p>
  </div>
{/if}

{#if lastReport?.schedule?.length}
  <div class="card">
    <h3>Расписание</h3>
    <ul class="list">
      {#each lastReport.schedule as row}
        <li>
          <strong>{deptLabel(row.department)}</strong> {row.start_at} → {row.deadline}
        </li>
      {/each}
    </ul>
  </div>
{/if}

<div class="card">
  <h2>История</h2>
  <ul class="list">
    {#each directives as d (d.id)}
      <li>
        <button class="ghost history-btn" onclick={() => (lastReport = d)}>
          [{d.status}] {d.brief.slice(0, 80)}{#if d.brief.length > 80}…{/if}
        </button>
      </li>
    {:else}
      <li class="muted">Пока пусто</li>
    {/each}
  </ul>
</div>

<style>
  .chief-hint {
    color: var(--muted);
    font-size: 0.85rem;
    margin-bottom: 0.75rem;
    line-height: 1.5;
  }
  .cmd-hint {
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 0.75rem;
    line-height: 1.6;
  }
  .cmd-hint code {
    background: var(--surface2);
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
  }
  .btn-row {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .deliverable-card {
    border-color: #2a5c3a;
  }
  .report-pre {
    white-space: pre-wrap;
    font-family: inherit;
    font-size: 0.9rem;
    line-height: 1.55;
    background: var(--surface2);
    padding: 1rem;
    border-radius: 8px;
    max-height: 560px;
    overflow-y: auto;
    margin: 0;
  }
  .history-btn {
    text-align: left;
    padding: 0.25rem 0;
    width: 100%;
  }
</style>
