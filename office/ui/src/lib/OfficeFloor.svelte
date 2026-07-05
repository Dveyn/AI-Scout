<script>
  import { onMount } from 'svelte';
  import { createWorkstation, fetchActivity, fetchRegistry, runWorkstation } from './api.js';

  let { overview, onchange, ontoast } = $props();

  const deptMeta = {
    executive: { label: 'Управление', icon: '👔', tint: '#3d2e1f' },
    marketing: { label: 'Маркетинг', icon: '📣', tint: '#1e2a3d' },
    sales: { label: 'Продажи', icon: '💼', tint: '#1e3d2a' },
    leadgen: { label: 'Лидоген', icon: '🎯', tint: '#3d1e2e' },
    production: { label: 'Продакшн', icon: '⚙️', tint: '#2a1e3d' },
  };

  const roleEmoji = {
    coo: '👔',
    executive_assistant: '📋',
    cmo: '📊',
    marketer: '📈',
    targetologist: '🎯',
    smm: '📱',
    seo: '🔍',
    analytics: '📉',
    head_sales: '💼',
    head_leadgen: '🗺️',
    head_production: '🏗️',
    scout: '🛰️',
    pm: '📋',
    designer: '🎨',
    frontend: '💻',
    backend: '🔧',
    qa: '✅',
    account_manager: '🤝',
  };

  let presets = $state({});
  let selected = $state(null);
  let panel = $state('none');
  let brief = $state('');
  let presetId = $state('targetologist');
  let hireName = $state('');
  let busy = $state(false);
  let activity = $state([]);
  let lastResult = $state('');

  const stepLabels = {
    start: '▶ Старт',
    run: '⚙ Запуск',
    assign: '📤 Отделам',
    llm: '🤖 GPTunnel',
    search: '🔍 Поиск',
    queue: '📤 Очередь',
    done: '✅ Готово',
    error: '❌ Ошибка',
  };

  let rooms = $derived.by(() => {
    const map = {};
    for (const d of overview?.departments ?? []) {
      map[d.slug] = { dept: d, agents: [] };
    }
    for (const w of overview?.workstations ?? []) {
      if (!map[w.department_slug]) {
        map[w.department_slug] = { dept: { slug: w.department_slug }, agents: [] };
      }
      map[w.department_slug].agents.push(w);
    }
    const order = ['executive', 'marketing', 'sales', 'leadgen', 'production'];
    return order.filter((s) => map[s]).map((slug) => [slug, map[slug]]);
  });

  onMount(async () => {
    const data = await fetchRegistry();
    presets = data.presets ?? {};
  });

  async function openAgent(agent) {
    selected = agent;
    panel = 'task';
    brief = '';
    lastResult = agent.last_result || '';
    activity = [];
    try {
      const data = await fetchActivity(agent.id);
      activity = data.activity ?? [];
      if (data.workstation?.last_result) lastResult = data.workstation.last_result;
    } catch {
      /* ignore */
    }
  }

  function openHire(slug) {
    selected = { department_slug: slug };
    panel = 'hire';
    presetId = Object.keys(presets).find((id) => presets[id]?.department === slug) ?? 'targetologist';
    hireName = '';
  }

  function closePanel() {
    panel = 'none';
    selected = null;
  }

  function statusLabel(s) {
    const m = {
      idle: 'Свободен',
      working: 'В работе',
      waiting_approval: 'Ждёт OK',
      blocked: 'Стоп',
      done: 'Готово',
    };
    return m[s] ?? s;
  }

  async function submitTask() {
    if (!selected?.id || !brief.trim()) return;
    busy = true;
    lastResult = '';
    try {
      const res = await runWorkstation(selected.id, brief);
      lastResult = res.summary || res.error || res.mode || 'Готово';
      if (res.error) {
        ontoast?.(res.error);
      } else {
        ontoast?.('Задача выполнена — см. журнал');
      }
      const data = await fetchActivity(selected.id);
      activity = data.activity ?? [];
      if (data.workstation) selected = { ...selected, ...data.workstation };
      onchange?.();
    } catch (e) {
      lastResult = e.message;
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }

  async function submitHire() {
    busy = true;
    try {
      await createWorkstation(presetId, hireName, '');
      ontoast?.('Сотрудник вышел на работу');
      onchange?.();
      closePanel();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }
</script>

<div class="office-wrap">
  <div class="office-sign">ВЕБШТРИХ HQ</div>

  <div class="office-floor">
    <div class="room room--meeting">
      <div class="room__label">🪑 Переговорная</div>
      <div class="meeting-table"></div>
      <p class="room__hint">Standup → вкладка «Совещания»</p>
    </div>

    {#each rooms as [slug, { dept, agents }] (slug)}
      {@const meta = deptMeta[slug] ?? { label: slug, icon: '🏢', tint: '#222' }}
      <section class="room room--dept" style="--room-tint: {meta.tint}">
        <div class="room__label">{meta.icon} {meta.label}</div>
        <div class="desks">
          {#each agents as agent (agent.id)}
            <button
              type="button"
              class="desk desk--occupied status-{agent.status}"
              onclick={() => openAgent(agent)}
              title="{agent.role}"
            >
              <div class="desk__furniture">
                <div class="monitor"></div>
                <div class="chair"></div>
              </div>
              <div class="avatar">{roleEmoji[agent.preset_id] ?? meta.icon}</div>
              <div class="desk__name">{agent.name}</div>
              <div class="desk__status">{statusLabel(agent.status)}</div>
            </button>
          {/each}
          <button type="button" class="desk desk--empty" onclick={() => openHire(slug)}>
            <span class="desk__plus">+</span>
            <span>Нанять</span>
          </button>
        </div>
      </section>
    {/each}

    <div class="room room--ceo">
      <div class="room__label">🎩 Кабинет CEO</div>
      <div class="ceo-desk">
        <div class="avatar avatar--ceo">🎩</div>
        <div class="desk__name">Вы</div>
        <div class="desk__status">Директор</div>
      </div>
    </div>
  </div>

  <p class="office-hint">Клик по столу — дать задачу · «+» — нанять из пресета</p>
</div>

{#if panel !== 'none'}
  <div class="panel-backdrop" onclick={closePanel} role="presentation"></div>
  <aside class="agent-panel">
    {#if panel === 'task' && selected}
      <h3>{selected.name}</h3>
      <p class="muted">{selected.role}</p>
      {#if selected.preset_id === 'coo'}
        <p class="panel-task muted" style="font-size:0.82rem">
          Одна задача → COO раздаёт отделам со сроками → вы получаете готовый результат.
        </p>
      {/if}
      <span class="badge {selected.status}">{statusLabel(selected.status)}</span>
      {#if selected.current_task}
        <p class="panel-task"><strong>Сейчас:</strong> {selected.current_task}</p>
      {/if}
      {#if lastResult}
        <div class="panel-result">
          <strong>Результат</strong>
          <p>{lastResult}</p>
        </div>
      {/if}
      {#if activity.length}
        <div class="activity-log">
          <strong>Журнал</strong>
          <ul>
            {#each activity as row (row.id)}
              <li>
                <span class="act-step">{stepLabels[row.step] ?? row.step}</span>
                {row.message}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
      <label class="form-row">
        <span>Задача от CEO</span>
        <textarea bind:value={brief} placeholder="Что нужно сделать?"></textarea>
      </label>
      <div class="panel-actions">
        <button onclick={submitTask} disabled={busy || !brief.trim()}>
          {busy ? 'Выполняется…' : 'Отправить'}
        </button>
        <button class="ghost" onclick={closePanel}>Закрыть</button>
      </div>
    {:else if panel === 'hire'}
      <h3>Нанять в отдел</h3>
      <p class="muted">{deptMeta[selected?.department_slug]?.label ?? ''}</p>
      <label class="form-row">
        <span>Роль</span>
        <select bind:value={presetId}>
          {#each Object.entries(presets).filter(([, p]) => p.department === selected?.department_slug) as [id, p] (id)}
            <option value={id}>{p.role}</option>
          {/each}
        </select>
      </label>
      <label class="form-row">
        <span>Имя</span>
        <input bind:value={hireName} placeholder="Необязательно" />
      </label>
      <div class="panel-actions">
        <button onclick={submitHire} disabled={busy}>Нанять</button>
        <button class="ghost" onclick={closePanel}>Отмена</button>
      </div>
    {/if}
  </aside>
{/if}
