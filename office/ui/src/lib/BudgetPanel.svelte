<script>
  import { onMount } from 'svelte';
  import { fetchBudget } from './api.js';

  let budget = $state(null);

  onMount(async () => {
    budget = await fetchBudget();
  });

  let pct = $derived.by(() => {
    if (!budget?.global_limit_rub) return 0;
    return Math.min(100, (budget.global_spent_rub / budget.global_limit_rub) * 100);
  });
</script>

{#if budget}
  <div class="stats">
    <div class="stat">
      <div class="val">{budget.global_spent_rub?.toFixed?.(1)} ₽</div>
      <div class="lbl">Office сегодня</div>
    </div>
    <div class="stat">
      <div class="val">{budget.global_limit_rub?.toFixed?.(0)} ₽</div>
      <div class="lbl">Лимит office</div>
    </div>
    <div class="stat">
      <div class="val">{budget.scout_spent_rub?.toFixed?.(1)} ₽</div>
      <div class="lbl">Scout/GPTunnel</div>
    </div>
    <div class="stat">
      <div class="val">{budget.dept_limit_rub?.toFixed?.(0)} ₽</div>
      <div class="lbl">Лимит / отдел</div>
    </div>
  </div>

  <div class="card">
    <h2>Использование бюджета</h2>
    <div style="background:var(--surface2);border-radius:8px;height:12px;overflow:hidden">
      <div
        style="height:100%;width:{pct}%;background:{pct > 80 ? 'var(--danger)' : 'var(--accent)'};transition:width 0.3s"
      ></div>
    </div>
    <p style="margin-top:0.5rem;font-size:0.85rem;color:var(--muted)">
      Режим: {budget.provider} · {pct.toFixed(0)}% лимита
    </p>
  </div>

  <div class="card">
    <h2>Правила экономии</h2>
    <ul class="list">
      <li>KPI и отчёты — без LLM (локальный расчёт)</li>
      <li>Стратегия — gpt-4o, исполнение — gpt-4o-mini</li>
      <li>Hybrid: тяжёлая работа → Cursor webhooks</li>
      <li>Standup — только руководители отделов, не group-chat</li>
      <li>Бренд-контекст кэшируется в system prefix</li>
    </ul>
  </div>
{:else}
  <p>Загрузка…</p>
{/if}
