<script>
  let { overview } = $props();

  const deptLabels = {
    executive: 'Управление',
    marketing: 'Маркетинг',
    sales: 'Продажи',
    leadgen: 'Лидоген',
    production: 'Продакшн',
  };

  let byDept = $derived.by(() => {
    const map = {};
    for (const d of overview?.departments ?? []) {
      map[d.slug] = { dept: d, agents: [] };
    }
    for (const w of overview?.workstations ?? []) {
      if (!map[w.department_slug]) {
        map[w.department_slug] = { dept: { name: w.department_slug }, agents: [] };
      }
      map[w.department_slug].agents.push(w);
    }
    return Object.entries(map);
  });
</script>

<div class="agent-grid">
  {#each byDept as [slug, { dept, agents }]}
    <div class="card">
      <h2>{deptLabels[slug] ?? dept?.name ?? slug}</h2>
      {#if agents.length === 0}
        <p style="color:var(--muted);font-size:0.85rem">Нет сотрудников — создайте рабочее место</p>
      {:else}
        {#each agents as a}
          <div class="agent-card" style="margin-bottom:0.5rem">
            <div class="role">{a.name}</div>
            <div class="dept">{a.role}</div>
            <span class="badge {a.status}">{a.status}</span>
            {#if a.current_task}
              <p style="font-size:0.75rem;margin-top:0.35rem;color:var(--muted)">{a.current_task}</p>
            {/if}
          </div>
        {/each}
      {/if}
    </div>
  {/each}
</div>
