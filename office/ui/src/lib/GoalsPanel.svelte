<script>
  import { createGoal, cascadeGoal } from './api.js';

  let { overview, onchange, ontoast } = $props();

  let horizon = $state('week');
  let text = $state('');
  let busy = $state(false);

  async function submit() {
    if (!text.trim()) return;
    busy = true;
    try {
      await createGoal(horizon, text.trim());
      text = '';
      ontoast?.('Цель создана');
      onchange?.();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }

  async function cascade(id) {
    busy = true;
    try {
      const res = await cascadeGoal(id);
      ontoast?.(`Декомпозиция: ${res.child_goals?.length ?? 0} подцелей`);
      onchange?.();
    } catch (e) {
      ontoast?.(e.message);
    } finally {
      busy = false;
    }
  }
</script>

<div class="card">
  <h2>Новая цель CEO</h2>
  <div class="form-row">
    <label>Горизонт</label>
    <select bind:value={horizon}>
      <option value="day">День</option>
      <option value="week">Неделя</option>
      <option value="month">Месяц</option>
    </select>
  </div>
  <div class="form-row">
    <label>Формулировка</label>
    <textarea bind:value={text} placeholder="Например: 5 новых сделок из аутрича"></textarea>
  </div>
  <button onclick={submit} disabled={busy}>Создать цель</button>
</div>

<div class="card">
  <h2>Активные цели</h2>
  <ul class="list">
    {#each overview?.goals ?? [] as g}
      <li>
        <strong>[{g.horizon}]</strong> {g.text}
        <div style="margin-top:0.35rem">
          <button class="ghost" style="font-size:0.8rem;padding:0.25rem 0.5rem" onclick={() => cascade(g.id)} disabled={busy}>
            Декомпозировать (COO)
          </button>
        </div>
      </li>
    {:else}
      <li style="color:var(--muted)">Целей пока нет</li>
    {/each}
  </ul>
</div>
