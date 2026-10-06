/**
 * Main Web Application Controller for IRC / Discord Statistics Dashboard
 */

document.addEventListener('DOMContentLoaded', () => {
  let statsData = null;
  let networkGraph = null;

  // UI Elements
  const themeToggleBtn = document.getElementById('themeToggleBtn');
  const refreshBtn = document.getElementById('refreshBtn');
  const minStrengthSlider = document.getElementById('minStrengthSlider');
  const strengthVal = document.getElementById('strengthVal');
  const graphSearchInput = document.getElementById('graphSearchInput');
  const resetGraphBtn = document.getElementById('resetGraphBtn');
  const togglePhysicsBtn = document.getElementById('togglePhysicsBtn');
  const zoomInBtn = document.getElementById('zoomInBtn');
  const zoomOutBtn = document.getElementById('zoomOutBtn');
  const tableSearchInput = document.getElementById('tableSearchInput');
  const userModal = document.getElementById('userModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const toast = document.getElementById('toast');

  // Initialize Theme from localStorage
  const savedTheme = localStorage.getItem('irc_stats_theme') || 'theme-modern';
  setTheme(savedTheme);

  themeToggleBtn.addEventListener('click', (e) => {
    e.preventDefault();
    const currentTheme = document.body.classList.contains('theme-retro') ? 'theme-retro' : 'theme-modern';
    const nextTheme = currentTheme === 'theme-retro' ? 'theme-modern' : 'theme-retro';
    setTheme(nextTheme);
  });

  function setTheme(theme) {
    document.body.classList.remove('theme-retro', 'theme-modern');
    document.body.classList.add(theme);
    localStorage.setItem('irc_stats_theme', theme);

    const isRetro = theme === 'theme-retro';
    themeToggleBtn.querySelector('.theme-icon').textContent = isRetro ? '✨' : '📼';
    themeToggleBtn.querySelector('.theme-text').textContent = isRetro ? 'Modern Theme' : 'Retro IRC Theme';

    if (networkGraph) {
      networkGraph.render();
    }
  }

  // Toast Notification
  function showToast(message, duration = 3000) {
    toast.textContent = message;
    toast.style.display = 'block';
    setTimeout(() => {
      toast.style.display = 'none';
    }, duration);
  }

  // Load Data from API or static data.json
  async function loadData() {
    try {
      let res;
      try {
        res = await fetch('/api/stats');
      } catch (e) {
        // Fallback to static data.json if not on server
        res = await fetch('data.json');
      }

      if (!res.ok) {
        res = await fetch('data.json');
      }

      statsData = await res.json();
      renderDashboard(statsData);
    } catch (err) {
      console.error('Failed to load statistics data:', err);
      showToast('⚠️ Could not load data. Ensure server or data.json is accessible.');
    }
  }

  // Refresh data via API
  refreshBtn.addEventListener('click', async () => {
    refreshBtn.disabled = true;
    refreshBtn.innerHTML = '⏳ Scanning logs...';
    try {
      const res = await fetch('/api/refresh', { method: 'POST' });
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        statsData = json.data;
        renderDashboard(statsData);
        showToast('✅ Stats updated from raw Discord logs & RAG memory!');
      } else {
        await loadData();
        showToast('✅ Refreshed statistics!');
      }
    } catch (err) {
      console.error('Refresh error:', err);
      showToast('⚠️ Failed to refresh live data.');
    } finally {
      refreshBtn.disabled = false;
      refreshBtn.innerHTML = '<span class="refresh-icon">🔄</span> Refresh Stats';
    }
  });

  function renderDashboard(data) {
    if (!data || !data.overview) return;

    // Header & Meta
    document.getElementById('channelTitle').innerHTML = `Channel Statistics for <span class="highlight-channel">${data.channel}</span>`;
    document.getElementById('channelMeta').textContent = 
      `Period: ${data.period_start} to ${data.period_end} (${data.timespan_days} days) • Generated: ${data.generated_display || 'Just now'}`;

    // KPI Cards
    document.getElementById('kpiLines').textContent = data.overview.total_messages.toLocaleString();
    document.getElementById('kpiLinesAvg').textContent = `${data.overview.avg_messages_per_day} lines/day`;
    document.getElementById('kpiWords').textContent = data.overview.total_words.toLocaleString();
    document.getElementById('kpiWordsAvg').textContent = `${data.overview.avg_words_per_message} words/line`;
    document.getElementById('kpiUsers').textContent = data.overview.unique_participants;
    document.getElementById('kpiHour').textContent = data.overview.busiest_hour.split(' - ')[0];
    document.getElementById('kpiDay').textContent = `Peak Day: ${data.overview.busiest_day}`;
    document.getElementById('kpiDays').textContent = `${data.timespan_days} Days`;
    document.getElementById('kpiDates').textContent = `${data.period_start} – ${data.period_end}`;

    // Reveal interactive container if JavaScript is active
    const interactiveContainer = document.getElementById('interactiveCanvasContainer');
    const staticWrapper = document.getElementById('staticNetworkWrapper');
    if (interactiveContainer) {
      interactiveContainer.style.display = 'block';
    }
    if (staticWrapper) {
      staticWrapper.style.display = 'none';
    }

    // Initialize Network Graph
    if (!networkGraph) {
      networkGraph = new NetworkGraph('networkCanvas', 'networkCanvasWrapper', 'graphTooltip');
    }
    networkGraph.setData(data.network);

    // Setup Network Controls
    minStrengthSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value, 10);
      strengthVal.textContent = val;
      networkGraph.setMinStrength(val);
    });

    graphSearchInput.addEventListener('input', (e) => {
      networkGraph.setSearch(e.target.value);
    });

    resetGraphBtn.addEventListener('click', () => {
      networkGraph.resetView();
    });

    togglePhysicsBtn.addEventListener('click', () => {
      const isRunning = networkGraph.togglePhysics();
      togglePhysicsBtn.textContent = isRunning ? '⏸️ Pause Layout' : '▶️ Resume Layout';
    });

    zoomInBtn.addEventListener('click', () => networkGraph.zoom(1.2));
    zoomOutBtn.addEventListener('click', () => networkGraph.zoom(0.83));

    // Render Charts
    Charts.renderTopTalkers('topTalkersChart', data.participants, 15);
    Charts.renderHourly('hourlyChart', data.hourly_distribution);
    Charts.renderDaily('dailyChart', data.daily_distribution);
    Charts.renderTimeline('timelineChart', data.timeline);

    // Badges
    document.getElementById('peakHourBadge').textContent = `Peak: ${data.overview.busiest_hour}`;
    document.getElementById('peakDayBadge').textContent = `Peak: ${data.overview.busiest_day}`;

    // Render Leaderboard Table
    renderLeaderboard(data.participants);

    // Render Superlatives (Big Numbers)
    renderSuperlatives(data.superlatives);
  }

  function renderLeaderboard(participants) {
    const tbody = document.getElementById('leaderboardBody');
    tbody.innerHTML = '';

    const maxLines = participants.length ? participants[0].lines : 1;

    participants.forEach((p) => {
      const tr = document.createElement('tr');
      tr.dataset.username = p.name.toLowerCase();

      // Rank badge
      let rankHtml = `#${p.rank}`;
      if (p.rank === 1) rankHtml = `<span class="td-rank-badge rank-1">🥇</span>`;
      else if (p.rank === 2) rankHtml = `<span class="td-rank-badge rank-2">🥈</span>`;
      else if (p.rank === 3) rankHtml = `<span class="td-rank-badge rank-3">🥉</span>`;

      // Progress bar fill %
      const barPct = Math.min(100, Math.max(3, (p.lines / maxLines) * 100));

      tr.innerHTML = `
        <td class="td-rank">${rankHtml}</td>
        <td class="td-nick">${escapeHtml(p.name)}</td>
        <td style="font-family: monospace; font-weight: 600;">${p.lines.toLocaleString()}</td>
        <td>
          <div class="bar-container">
            <div class="bar-track">
              <div class="bar-fill" style="width: ${barPct}%;"></div>
            </div>
          </div>
        </td>
        <td style="font-family: monospace; color: var(--accent-cyan); font-weight: 600;">${p.percentage}%</td>
        <td style="font-family: monospace;">${p.words.toLocaleString()}</td>
        <td style="font-family: monospace;">${p.avg_words_per_line}</td>
        <td style="font-family: monospace; font-size: 0.8rem; color: var(--text-muted);">${p.peak_hour_formatted}</td>
        <td class="td-quote" title="${escapeHtml(p.best_quote)}">
          ${p.best_quote ? `"${escapeHtml(p.best_quote)}"` : '—'}
        </td>
        <td>
          <button class="btn-profile" onclick="event.stopPropagation(); window.dispatchEvent(new CustomEvent('open-user-modal', {detail: '${escapeHtml(p.name)}'}))">
            Dossier ↗
          </button>
        </td>
      `;

      tr.addEventListener('click', () => {
        openUserModal(p.name);
      });

      tbody.appendChild(tr);
    });

    // Table Search Filter
    tableSearchInput.addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      const rows = tbody.querySelectorAll('tr');
      rows.forEach((row) => {
        if (!q || row.dataset.username.includes(q)) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    });
  }

  function renderSuperlatives(superlatives) {
    const grid = document.getElementById('superlativesGrid');
    grid.innerHTML = '';

    (superlatives || []).forEach((s) => {
      const card = document.createElement('div');
      card.className = 'award-card';
      card.innerHTML = `
        <div class="award-top">
          <div class="award-icon">${s.icon}</div>
          <div class="award-name">${s.award}</div>
        </div>
        <div class="award-winner">${escapeHtml(s.user)}</div>
        <div class="award-metric">${s.metric}</div>
        <div class="award-desc">${s.description}</div>
      `;

      // If award winner is a user, click opens their modal
      if (statsData && statsData.participants.some(p => p.name === s.user)) {
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => openUserModal(s.user));
      }

      grid.appendChild(card);
    });
  }

  // User Profile / Dossier Modal
  function openUserModal(username) {
    if (!statsData || !statsData.participants) return;
    const user = statsData.participants.find(p => p.name.toLowerCase() === username.toLowerCase());
    if (!user) return;

    document.getElementById('modalAvatar').textContent = user.name.charAt(0).toUpperCase();
    document.getElementById('modalName').textContent = user.name;
    document.getElementById('modalRank').textContent = `Rank #${user.rank} • ${user.percentage}% of all channel lines (${user.lines.toLocaleString()} lines)`;
    document.getElementById('modalLines').textContent = user.lines.toLocaleString();
    document.getElementById('modalWords').textContent = user.words.toLocaleString();
    document.getElementById('modalWPL').textContent = user.avg_words_per_line;
    document.getElementById('modalPeakHour').textContent = `${user.peak_hour}:00`;

    // Render Top Partners
    const partnersContainer = document.getElementById('modalPartners');
    partnersContainer.innerHTML = '';
    if (user.top_partners && user.top_partners.length) {
      user.top_partners.forEach(partner => {
        const item = document.createElement('div');
        item.className = 'partner-item';
        item.innerHTML = `
          <span class="partner-name">${escapeHtml(partner.name)}</span>
          <span class="partner-strength">⚡ ${partner.strength} interactions</span>
        `;
        item.querySelector('.partner-name').addEventListener('click', (e) => {
          e.stopPropagation();
          openUserModal(partner.name);
        });
        partnersContainer.appendChild(item);
      });
    } else {
      partnersContainer.innerHTML = '<div style="color:var(--text-dim); font-size:0.85rem;">No conversational pairs recorded.</div>';
    }

    // Render Sparkline
    Charts.renderUserSparkline('modalSparkline', user.hourly);

    // Render Quotes
    const quotesContainer = document.getElementById('modalQuotes');
    quotesContainer.innerHTML = '';
    if (user.quotes && user.quotes.length) {
      user.quotes.slice(0, 6).forEach(q => {
        const bubble = document.createElement('div');
        bubble.className = 'quote-bubble';
        bubble.textContent = `"${q}"`;
        quotesContainer.appendChild(bubble);
      });
    } else {
      quotesContainer.innerHTML = '<div style="color:var(--text-dim); font-size:0.85rem;">No notable quotes recorded.</div>';
    }

    userModal.style.display = 'flex';
  }

  function closeUserModal() {
    userModal.style.display = 'none';
  }

  modalCloseBtn.addEventListener('click', closeUserModal);
  userModal.addEventListener('click', (e) => {
    if (e.target === userModal) closeUserModal();
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && userModal.style.display === 'flex') {
      closeUserModal();
    }
  });

  // Listen for custom modal open event (from graph or charts)
  window.addEventListener('open-user-modal', (e) => {
    openUserModal(e.detail);
  });

  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Load initial data
  loadData();
});
