// 月白 AI Agent · 前端交互
// ============ Tab 切换 ============
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.chat-pane').forEach(p => p.classList.toggle('active', p.dataset.pane === target));
  });
});

// ============ 平滑滚动 ============
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const target = document.querySelector(a.getAttribute('href'));
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ============ 状态:探测 /healthz ============
(async () => {
  try {
    const r = await fetch('/healthz');
    if (r.ok) {
      const data = await r.json();
      console.log('[月白] 后端健康 ✅', data);
    }
  } catch (e) {
    console.log('[月白] 后端未就绪(部署到 serverless 后会自动生效)');
  }
})();
