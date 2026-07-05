<script>
  import { onMount } from 'svelte';
  import { createWorkstation, fetchRegistry, runWorkstation } from './api.js';

  let { overview, onchange, ontoast } = $props();

  let presets = $state({});
  let presetId = $state('targetologist');
  let customPrompt = $state('');
  let name = $state('');
  let brief = $state('');
  let selectedId = $state('');
  let busy = $state(false);

  onMount(async () => {
    const data = await fetchRegistry();
    presets = data.presets ?? {};
    if (!presetId && Object.keys(presets).length) {
      presetId = Object.keys(presets)[0];
    }
  });

  async function create() {
    busy = true;
    try {
      await createWorkstation(presetId, name, customPrompt);
      ontoast?.('Рабочее место создано');
      onchange?.();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }

  async function run() {
    if (!selectedId || !brief.trim()) return;
    busy = true;
    try {
      const res = await runWorkstation(selectedId, brief);
      ontoast?.(res.summary ?? res.mode ?? 'Готово');
      onchange?.();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }
</script>

<div class="grid-2">
  <div class="card">
    <h2>Создать рабочее место</h2>
    <div class="form-row">
      <label>Пресет</label>
      <select bind:value={presetId}>
        {#each Object.entries(presets) as [id, p]}
          <option value={id}>{p.role} ({p.department})</option>
        {/each}
      </select>
    </div>
    <div class="form-row">
      <label>Имя (опционально)</label>
      <input bind:value={name} placeholder="Мой таргетолог" />
    </div>
    <div class="form-row">
      <label>Доп. промпт</label>
      <textarea bind:value={customPrompt} placeholder="Особые инструкции CEO"></textarea>
    </div>
    <button onclick={create} disabled={busy}>Создать</button>
  </div>

  <div class="card">
    <h2>Дать задачу сотруднику</h2>
    <div class="form-row">
      <label>Сотрудник</label>
      <select bind:value={selectedId}>
        <option value="">— выберите —</option>
        {#each overview?.workstations ?? [] as w}
          <option value={w.id}>{w.name} · {w.role}</option>
        {/each}
      </select>
    </div>
    <div class="form-row">
      <label>Задача</label>
      <textarea bind:value={brief} placeholder="Подготовь рекламную кампанию на B2B порталы"></textarea>
    </div>
    <button onclick={run} disabled={busy || !selectedId}>Выполнить</button>
  </div>
</div>
