/**
 * Zero-dependency SVG Chart Renderer
 * Generates beautiful, responsive charts for:
 * 1. Top Talkers Bar Chart
 * 2. 24-Hour Activity Histogram (with daypart gradients & peak highlights)
 * 3. Day of the Week Activity Chart
 * 4. Timeline Message Volume Area Chart
 * 5. User Profile Modal Sparkline
 */

const Charts = {

  renderTopTalkers(containerId, participants, limit = 15) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const topList = participants.slice(0, limit);
    if (!topList.length) {
      container.innerHTML = '<div style="color:#64748b; padding:20px;">No participant data available.</div>';
      return;
    }

    const maxLines = topList[0].lines;
    const rowHeight = 36;
    const height = topList.length * rowHeight + 20;

    let svg = `
      <svg width="100%" height="${height}" viewBox="0 0 800 ${height}" preserveAspectRatio="none" style="display:block;">
        <defs>
          <linearGradient id="barGradTop" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#38bdf8"/>
            <stop offset="100%" stop-color="#818cf8"/>
          </linearGradient>
          <linearGradient id="barGradNormal" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#60a5fa"/>
            <stop offset="100%" stop-color="#3b82f6"/>
          </linearGradient>
        </defs>
    `;

    topList.forEach((user, idx) => {
      const y = idx * rowHeight + 10;
      const pctWidth = (user.lines / maxLines) * 540;
      const grad = idx < 3 ? 'url(#barGradTop)' : 'url(#barGradNormal)';

      svg += `
        <g class="chart-row" style="cursor: pointer;" onclick="window.dispatchEvent(new CustomEvent('open-user-modal', {detail: '${user.name}'}))">
          <!-- Rank & Name -->
          <text x="10" y="${y + 18}" fill="#94a3b8" font-size="12" font-family="monospace" font-weight="700">#${user.rank}</text>
          <text x="40" y="${y + 18}" fill="#f1f5f9" font-size="13" font-weight="600">${user.name.length > 15 ? user.name.slice(0, 14) + '…' : user.name}</text>
          
          <!-- Bar Track -->
          <rect x="170" y="${y + 6}" width="540" height="16" rx="4" fill="rgba(255,255,255,0.05)" />
          
          <!-- Bar Fill -->
          <rect x="170" y="${y + 6}" width="${Math.max(6, pctWidth)}" height="16" rx="4" fill="${grad}">
            <title>${user.name}: ${user.lines.toLocaleString()} lines (${user.percentage}%)</title>
          </rect>
          
          <!-- Count & Pct -->
          <text x="${180 + Math.max(6, pctWidth) + 10}" y="${y + 19}" fill="#cbd5e1" font-size="12" font-family="monospace" font-weight="600">
            ${user.lines.toLocaleString()} <tspan fill="#64748b">(${user.percentage}%)</tspan>
          </text>
        </g>
      `;
    });

    svg += '</svg>';
    container.innerHTML = svg;
  },

  renderHourly(containerId, hourlyData) {
    const container = document.getElementById(containerId);
    if (!container || !hourlyData) return;

    const maxCount = Math.max(...hourlyData.map(d => d.count), 1);
    const height = 180;
    const width = 600;
    const barWidth = 18;
    const gap = (width - 40 - (24 * barWidth)) / 23;

    // Daypart colors
    const getBarColor = (hour) => {
      if (hour < 6) return '#818cf8';   // Night
      if (hour < 12) return '#38bdf8';  // Morning
      if (hour < 18) return '#fbbf24';  // Afternoon
      return '#f472b6';                 // Evening
    };

    let svg = `
      <svg width="100%" height="${height + 30}" viewBox="0 0 ${width} ${height + 30}" style="display:block;">
    `;

    // Horizontal guide lines
    for (let i = 1; i <= 3; i++) {
      const gy = height - (height * (i / 4));
      svg += `<line x1="30" y1="${gy}" x2="${width - 10}" y2="${gy}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" />`;
    }

    hourlyData.forEach((d, i) => {
      const x = 35 + i * (barWidth + gap);
      const barHeight = Math.max(4, (d.count / maxCount) * (height - 20));
      const y = height - barHeight;
      const color = getBarColor(d.hour);

      svg += `
        <g class="chart-bar-hover">
          <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="3" fill="${color}">
            <title>${d.label}: ${d.count.toLocaleString()} messages (${d.percentage}%)</title>
          </rect>
          ${i % 2 === 0 ? `<text x="${x + barWidth / 2}" y="${height + 18}" text-anchor="middle" fill="#64748b" font-size="10" font-family="monospace">${d.hour}</text>` : ''}
        </g>
      `;
    });

    svg += '</svg>';
    container.innerHTML = svg;
  },

  renderDaily(containerId, dailyData) {
    const container = document.getElementById(containerId);
    if (!container || !dailyData) return;

    const maxCount = Math.max(...dailyData.map(d => d.count), 1);
    const height = 180;
    const width = 500;
    const barWidth = 42;
    const gap = (width - 40 - (7 * barWidth)) / 6;

    let svg = `
      <svg width="100%" height="${height + 30}" viewBox="0 0 ${width} ${height + 30}" style="display:block;">
    `;

    dailyData.forEach((d, i) => {
      const x = 20 + i * (barWidth + gap);
      const barHeight = Math.max(6, (d.count / maxCount) * (height - 25));
      const y = height - barHeight;

      svg += `
        <g class="chart-bar-hover">
          <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="4" fill="#38bdf8">
            <title>${d.day}: ${d.count.toLocaleString()} messages (${d.percentage}%)</title>
          </rect>
          <text x="${x + barWidth / 2}" y="${y - 6}" text-anchor="middle" fill="#cbd5e1" font-size="11" font-family="monospace" font-weight="600">${d.percentage}%</text>
          <text x="${x + barWidth / 2}" y="${height + 18}" text-anchor="middle" fill="#94a3b8" font-size="11" font-weight="600">${d.day.slice(0, 3)}</text>
        </g>
      `;
    });

    svg += '</svg>';
    container.innerHTML = svg;
  },

  renderTimeline(containerId, timelineData) {
    const container = document.getElementById(containerId);
    if (!container || !timelineData || !timelineData.length) return;

    const height = 120;
    const width = 900;
    const maxVal = Math.max(...timelineData.map(d => d.count), 10);
    const stepX = (width - 40) / Math.max(1, timelineData.length - 1);

    // Build path points
    let points = [];
    timelineData.forEach((d, i) => {
      const x = 20 + i * stepX;
      const y = height - 15 - (d.count / maxVal) * (height - 35);
      points.push(`${x},${y}`);
    });

    const pathData = 'M ' + points.join(' L ');
    const areaData = `${pathData} L ${20 + (timelineData.length - 1) * stepX},${height - 15} L 20,${height - 15} Z`;

    let svg = `
      <svg width="100%" height="${height + 25}" viewBox="0 0 ${width} ${height + 25}" style="display:block;">
        <defs>
          <linearGradient id="timelineGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="rgba(56, 189, 248, 0.4)"/>
            <stop offset="100%" stop-color="rgba(56, 189, 248, 0.0)"/>
          </linearGradient>
        </defs>
        
        <!-- Area fill -->
        <path d="${areaData}" fill="url(#timelineGrad)" />
        
        <!-- Line stroke -->
        <path d="${pathData}" fill="none" stroke="#38bdf8" stroke-width="2.5" />
    `;

    // Data points & hover tooltips
    timelineData.forEach((d, i) => {
      if (i % Math.ceil(timelineData.length / 15) === 0 || i === timelineData.length - 1) {
        const x = 20 + i * stepX;
        const y = height - 15 - (d.count / maxVal) * (height - 35);
        svg += `
          <circle cx="${x}" cy="${y}" r="3.5" fill="#ffffff" stroke="#0284c7" stroke-width="2">
            <title>${d.date}: ${d.count} messages</title>
          </circle>
          <text x="${x}" y="${height + 14}" text-anchor="middle" fill="#64748b" font-size="10" font-family="monospace">${d.date.slice(5)}</text>
        `;
      }
    });

    svg += '</svg>';
    container.innerHTML = svg;
  },

  renderUserSparkline(containerId, hourlyCounts) {
    const container = document.getElementById(containerId);
    if (!container || !hourlyCounts) return;

    const maxCount = Math.max(...hourlyCounts, 1);
    const height = 60;
    const width = 450;
    const barWidth = 12;
    const gap = (width - (24 * barWidth)) / 23;

    let svg = `
      <svg width="100%" height="${height + 18}" viewBox="0 0 ${width} ${height + 18}" style="display:block;">
    `;

    hourlyCounts.forEach((cnt, h) => {
      const x = h * (barWidth + gap);
      const bHeight = Math.max(2, (cnt / maxCount) * (height - 10));
      const y = height - bHeight;

      const hourStr = String(h).padStart(2, '0') + ':00';
      svg += `
        <rect x="${x}" y="${y}" width="${barWidth}" height="${bHeight}" rx="2" fill="#38bdf8">
          <title>${hourStr} - ${cnt} lines</title>
        </rect>
        ${h % 4 === 0 ? `<text x="${x + barWidth/2}" y="${height + 14}" text-anchor="middle" fill="#64748b" font-size="9" font-family="monospace">${h}</text>` : ''}
      `;
    });

    svg += '</svg>';
    container.innerHTML = svg;
  }
};
