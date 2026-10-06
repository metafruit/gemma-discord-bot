/**
 * User Connections Network Graph Engine (mIRCStats Relation Map)
 * High-performance HTML5 Canvas Force-Directed Network Graph with zero dependencies.
 * Handles drag, pan, zoom, hover highlighting, cluster physics, and threshold filtering.
 */

class NetworkGraph {
  constructor(canvasId, wrapperId, tooltipId) {
    this.canvas = document.getElementById(canvasId);
    this.wrapper = document.getElementById(wrapperId);
    this.tooltip = document.getElementById(tooltipId);
    this.ctx = this.canvas.getContext('2d');

    this.rawNodes = [];
    this.rawLinks = [];
    this.nodes = [];
    this.links = [];
    this.nodeMap = new Map();

    // Camera transform
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;

    // Physics parameters
    this.physicsRunning = true;
    this.minStrength = 2;
    this.searchQuery = '';

    // Interaction state
    this.hoveredNode = null;
    this.hoveredLink = null;
    this.draggedNode = null;
    this.isPanning = false;
    this.panStartX = 0;
    this.panStartY = 0;

    this.initCanvasSize();
    this.attachEvents();
  }

  initCanvasSize() {
    const rect = this.wrapper.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.width = rect.width || 900;
    this.height = rect.height || 540;

    this.canvas.width = this.width * dpr;
    this.canvas.height = this.height * dpr;
    this.ctx.resetTransform?.();
    this.ctx.scale(dpr, dpr);

    // Initial center camera
    this.panX = this.width / 2;
    this.panY = this.height / 2;
  }

  setData(networkData) {
    this.rawNodes = networkData.nodes || [];
    this.rawLinks = networkData.links || [];
    this.filterAndInitialize();
    this.startSimulation();
  }

  filterAndInitialize() {
    this.nodeMap.clear();

    // Calculate node radii based on line volume
    const maxLines = Math.max(...this.rawNodes.map(n => n.lines), 100);

    this.nodes = this.rawNodes.map((n, idx) => {
      // Circular initial distribution
      const angle = (idx / this.rawNodes.length) * Math.PI * 2;
      const radiusDist = 140 + (idx % 3) * 60;
      const radius = Math.max(12, Math.min(38, Math.round(10 + Math.sqrt(n.lines / maxLines) * 28)));

      const nodeObj = {
        ...n,
        x: Math.cos(angle) * radiusDist + (Math.random() - 0.5) * 40,
        y: Math.sin(angle) * radiusDist + (Math.random() - 0.5) * 40,
        vx: 0,
        vy: 0,
        radius: radius,
        mass: radius * 1.5
      };
      this.nodeMap.set(n.id, nodeObj);
      return nodeObj;
    });

    // Filter links by strength
    this.links = this.rawLinks
      .filter(l => l.weight >= this.minStrength)
      .map(l => ({
        ...l,
        sourceNode: this.nodeMap.get(l.source),
        targetNode: this.nodeMap.get(l.target)
      }))
      .filter(l => l.sourceNode && l.targetNode);
  }

  setMinStrength(strength) {
    this.minStrength = strength;
    this.links = this.rawLinks
      .filter(l => l.weight >= this.minStrength)
      .map(l => ({
        ...l,
        sourceNode: this.nodeMap.get(l.source),
        targetNode: this.nodeMap.get(l.target)
      }))
      .filter(l => l.sourceNode && l.targetNode);

    // Kick physics briefly to re-balance
    if (!this.physicsRunning) {
      this.stepPhysics();
      this.render();
    }
  }

  setSearch(query) {
    this.searchQuery = (query || '').trim().toLowerCase();
    this.render();
  }

  togglePhysics() {
    this.physicsRunning = !this.physicsRunning;
    if (this.physicsRunning) {
      this.startSimulation();
    }
    return this.physicsRunning;
  }

  resetView() {
    this.scale = 1.0;
    this.panX = this.width / 2;
    this.panY = this.height / 2;
    this.render();
  }

  zoom(factor) {
    this.scale = Math.max(0.3, Math.min(3.5, this.scale * factor));
    this.render();
  }

  startSimulation() {
    let iterations = 0;
    const animate = () => {
      if (!this.physicsRunning && !this.draggedNode) return;
      this.stepPhysics();
      this.render();
      iterations++;
      requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }

  stepPhysics() {
    const kRepel = 4500;
    const kSpring = 0.04;
    const damping = 0.85;
    const centerGravity = 0.015;

    // 1. Repulsion between all node pairs (anti-gravity)
    for (let i = 0; i < this.nodes.length; i++) {
      const n1 = this.nodes[i];
      for (let j = i + 1; j < this.nodes.length; j++) {
        const n2 = this.nodes[j];
        let dx = n2.x - n1.x;
        let dy = n2.y - n1.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const minDist = n1.radius + n2.radius + 15;

        // Force decreases with distance squared
        const force = (kRepel / (dist * dist)) * (dist < minDist ? 2.5 : 1);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        n1.vx -= fx / n1.mass;
        n1.vy -= fy / n1.mass;
        n2.vx += fx / n2.mass;
        n2.vy += fy / n2.mass;
      }
    }

    // 2. Spring tension along links (Hooke's law)
    for (const link of this.links) {
      const n1 = link.sourceNode;
      const n2 = link.targetNode;
      let dx = n2.x - n1.x;
      let dy = n2.y - n1.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;

      // Desired distance shorter for stronger bonds
      const targetDist = Math.max(70, 220 - Math.min(140, Math.sqrt(link.weight) * 16));
      const displacement = dist - targetDist;
      const springForce = displacement * kSpring;

      const fx = (dx / dist) * springForce;
      const fy = (dy / dist) * springForce;

      n1.vx += fx / n1.mass;
      n1.vy += fy / n1.mass;
      n2.vx -= fx / n2.mass;
      n2.vy -= fy / n2.mass;
    }

    // 3. Center gravity & update position
    for (const n of this.nodes) {
      if (n === this.draggedNode) continue;

      n.vx -= n.x * centerGravity;
      n.vy -= n.y * centerGravity;

      n.vx *= damping;
      n.vy *= damping;

      n.x += n.vx;
      n.y += n.vy;
    }
  }

  render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    // Connected neighbors set when hovering
    const connectedNodeIds = new Set();
    if (this.hoveredNode) {
      connectedNodeIds.add(this.hoveredNode.id);
      for (const l of this.links) {
        if (l.source === this.hoveredNode.id) connectedNodeIds.add(l.target);
        if (l.target === this.hoveredNode.id) connectedNodeIds.add(l.source);
      }
    }

    // Draw Links
    for (const link of this.links) {
      const isHighlighted = this.hoveredNode && 
        (link.source === this.hoveredNode.id || link.target === this.hoveredNode.id);
      const isDimmed = this.hoveredNode && !isHighlighted;

      ctx.beginPath();
      ctx.moveTo(link.sourceNode.x, link.sourceNode.y);
      ctx.lineTo(link.targetNode.x, link.targetNode.y);

      // Line thickness based on connection weight
      const strokeWidth = Math.min(8, Math.max(1.2, Math.sqrt(link.weight) * 0.7));
      ctx.lineWidth = strokeWidth;

      if (isHighlighted) {
        ctx.strokeStyle = '#38bdf8';
        ctx.shadowColor = '#38bdf8';
        ctx.shadowBlur = 6;
      } else if (isDimmed) {
        ctx.strokeStyle = 'rgba(75, 85, 99, 0.12)';
        ctx.shadowBlur = 0;
      } else {
        const opacity = Math.min(0.7, 0.15 + (link.weight / 150) * 0.55);
        ctx.strokeStyle = `rgba(129, 140, 248, ${opacity})`;
        ctx.shadowBlur = 0;
      }

      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    // Draw Nodes
    for (const n of this.nodes) {
      const isTarget = this.searchQuery && n.id.toLowerCase().includes(this.searchQuery);
      const isHovered = n === this.hoveredNode;
      const isConnected = connectedNodeIds.has(n.id);
      const isDimmed = (this.hoveredNode && !isConnected) || 
                       (this.searchQuery && !isTarget);

      ctx.save();
      ctx.globalAlpha = isDimmed ? 0.2 : 1.0;

      // Glow effect for selected / hovered
      if (isHovered || isTarget) {
        ctx.shadowColor = n.color || '#38bdf8';
        ctx.shadowBlur = 16;
      }

      // Outer Ring
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius + 3, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
      ctx.fill();

      // Node Body Circle
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      ctx.fillStyle = n.color || '#38bdf8';
      ctx.fill();

      ctx.lineWidth = isHovered ? 3 : 1.5;
      ctx.strokeStyle = isHovered ? '#ffffff' : 'rgba(0, 0, 0, 0.4)';
      ctx.stroke();

      ctx.shadowBlur = 0;

      // Inner Rank Icon or Rank Number
      ctx.fillStyle = '#ffffff';
      ctx.font = `bold ${Math.max(9, Math.round(n.radius * 0.7))}px monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(n.rank <= 3 ? ['🥇', '🥈', '🥉'][n.rank - 1] : `#${n.rank}`, n.x, n.y);

      // Node Label (Username)
      ctx.font = `600 ${Math.max(11, Math.round(11 * Math.sqrt(this.scale)))}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = isHovered || isTarget ? '#ffffff' : '#cbd5e1';
      ctx.fillText(n.label, n.x, n.y + n.radius + 5);

      ctx.restore();
    }

    ctx.restore();
  }

  screenToWorld(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const x = (clientX - rect.left - this.panX) / this.scale;
    const y = (clientY - rect.top - this.panY) / this.scale;
    return { x, y };
  }

  findNodeAt(wx, wy) {
    // Check backwards to hit top rendered nodes first
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i];
      const dx = wx - n.x;
      const dy = wy - n.y;
      if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 4) {
        return n;
      }
    }
    return null;
  }

  attachEvents() {
    window.addEventListener('resize', () => {
      this.initCanvasSize();
      this.render();
    });

    // Mouse Move (Hover & Drag)
    this.canvas.addEventListener('mousemove', (e) => {
      const { x, y } = this.screenToWorld(e.clientX, e.clientY);

      if (this.draggedNode) {
        this.draggedNode.x = x;
        this.draggedNode.y = y;
        this.draggedNode.vx = 0;
        this.draggedNode.vy = 0;
        this.render();
        return;
      }

      if (this.isPanning) {
        this.panX += e.movementX;
        this.panY += e.movementY;
        this.render();
        return;
      }

      const hit = this.findNodeAt(x, y);
      if (hit !== this.hoveredNode) {
        this.hoveredNode = hit;
        this.canvas.style.cursor = hit ? 'pointer' : 'grab';
        this.updateTooltip(e.clientX, e.clientY, hit);
        this.render();
      } else if (hit) {
        this.updateTooltip(e.clientX, e.clientY, hit);
      }
    });

    // Mouse Down
    this.canvas.addEventListener('mousedown', (e) => {
      const { x, y } = this.screenToWorld(e.clientX, e.clientY);
      const hit = this.findNodeAt(x, y);
      if (hit) {
        this.draggedNode = hit;
      } else {
        this.isPanning = true;
      }
    });

    // Mouse Up
    window.addEventListener('mouseup', () => {
      this.draggedNode = null;
      this.isPanning = false;
    });

    // Click Node -> Open User Modal
    this.canvas.addEventListener('click', (e) => {
      const { x, y } = this.screenToWorld(e.clientX, e.clientY);
      const hit = this.findNodeAt(x, y);
      if (hit) {
        window.dispatchEvent(new CustomEvent('open-user-modal', { detail: hit.id }));
      }
    });

    // Wheel Zoom
    this.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
      this.zoom(zoomFactor);
    }, { passive: false });
  }

  updateTooltip(clientX, clientY, node) {
    if (!node) {
      this.tooltip.style.display = 'none';
      return;
    }

    const rect = this.wrapper.getBoundingClientRect();
    const x = clientX - rect.left + 14;
    const y = clientY - rect.top + 14;

    this.tooltip.innerHTML = `
      <div style="font-weight: 700; font-size: 0.95rem; color: ${node.color || '#38bdf8'}">${node.label}</div>
      <div style="font-size: 0.8rem; color: #cbd5e1; margin-top: 3px;">
        Rank: <strong>#${node.rank}</strong> • Lines: <strong>${node.lines.toLocaleString()}</strong> (${node.percentage}%)
      </div>
      <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 4px;">
        Connected to <strong>${node.partners_count}</strong> chatter(s)
      </div>
      ${node.quote ? `<div style="font-size: 0.75rem; font-style: italic; color: #facc15; margin-top: 6px; border-left: 2px solid #facc15; padding-left: 6px;">"${node.quote.slice(0, 80)}..."</div>` : ''}
      <div style="font-size: 0.7rem; color: #38bdf8; margin-top: 6px; text-align: right;">Click to inspect profile ↗</div>
    `;

    this.tooltip.style.left = `${Math.min(x, rect.width - 290)}px`;
    this.tooltip.style.top = `${Math.min(y, rect.height - 120)}px`;
    this.tooltip.style.display = 'block';
  }
}
