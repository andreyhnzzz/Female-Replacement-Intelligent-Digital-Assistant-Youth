/* ═══════ F.R.I.D.A.Y OS — HUD client ═══════
   Escucha el bus por websocket y pinta. No decide nada. */

const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, '0');
/* MB -> unidad legible: 52184 MB no se lee, 51.0 GB si */
const size = mb => mb >= 1024000 ? (mb / 1048576).toFixed(1) + ' TB'
                 : mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB'
                 : mb.toFixed(0) + ' MB';

let ws, retry = 0, state = {}, wave = [], graphData = null;

/* ───────────── reloj ───────────── */
const DAYS = ['domingo','lunes','martes','miercoles','jueves','viernes','sabado'];
const MONS = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
setInterval(() => {
  const d = new Date();
  $('#clock').textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  $('#date').textContent = `${DAYS[d.getDay()]} ${d.getDate()} ${MONS[d.getMonth()]} ${d.getFullYear()}`;
}, 1000);

/* ───────────── websocket ───────────── */
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { retry = 0; chip('#c-link', 'enlace activo', true); };
  ws.onclose = () => {
    chip('#c-link', 'enlace caido', false);
    setTimeout(connect, Math.min(1000 * ++retry, 8000));
  };
  ws.onmessage = e => { try { handle(JSON.parse(e.data)); } catch (_) {} };
}

function send(type, extra = {}) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type, ...extra }));
}
setInterval(() => send('ping'), 2000);

/* ───────────── router de eventos ───────────── */
function handle(m) {
  if (m.vitals || m.vault || m.status) apply(m);

  switch (m.topic) {
    case 'hud.hello':
      apply(m); boot(m); break;

    case 'voice.ptt.down':
      pulse('busy'); $('#ptt-hint').classList.add('live');
      $('#a-state').textContent = 'grabando'; wave = []; break;

    case 'voice.ptt.up':
      $('#ptt-hint').classList.remove('live');
      $('#a-state').textContent = 'procesando';
      $('#a-last').textContent = `${m.duration}s`; break;

    case 'voice.ptt.discard':
      $('#ptt-hint').classList.remove('live');
      $('#a-state').textContent = 'inactivo'; pulse('');
      log('sys', 'muy corto, descartado'); break;

    case 'voice.stt.final':
      log('you', m.text);
      $('#a-state').textContent = 'inactivo';
      $('#a-last').textContent = `${m.duration || '?'}s · ${m.ms}ms · conf ${m.confidence}`;
      break;

    case 'voice.level':
      setLevel(m.level ?? 0); break;

    case 'router.decided':
      fireSkill(m.skill);
      $('#o-meta').textContent = `${m.skill} · ${m.how} · ${(m.confidence * 100 | 0)}%`;
      pulse('busy'); break;

    case 'skill.result':
      if (m.display) render(m.display);
      if (m.speak) log('fri', m.speak);
      $('#o-meta').textContent = `${m.skill} · ${m.ms}ms` + (m.writes?.length ? ` · ${m.writes.length} escritas` : '');
      pulse(''); break;

    case 'tts.speaking': pulse('talk'); $('#a-out').textContent = m.backend || '—'; break;
    case 'tts.done':     pulse(''); break;

    case 'core.error':
      log('err', m.message); pulse('err');
      setTimeout(() => pulse(''), 2500); break;

    case 'core.info':
      log('sys', m.message); break;
  }
}

/* ───────────── estado -> paneles ───────────── */
function apply(s) {
  state = { ...state, ...s };
  const v = s.vitals || {};

  ring('#g-cpu', v.cpu);
  ring('#g-ram', v.ram);
  ring('#g-disk', v.disk);
  if (v.uptime_h != null) $('#v-uptime').textContent = `${v.uptime_h} h`;
  if (v.procs != null) $('#v-procs').textContent = v.procs;
  $('#v-bat').textContent = v.battery != null
    ? `${v.battery}%${v.plugged ? ' ⚡' : ''}` : 'ac';
  if (v.net_sent_mb != null) $('#v-net').textContent =
    `${size(v.net_sent_mb)} / ${size(v.net_recv_mb)}`;

  const vt = s.vault || {};
  if (vt.notes != null) {
    $('#s-notes').textContent = vt.notes;
    $('#s-links').textContent = vt.links;
    $('#s-tags').textContent = vt.tags;
    $('#s-words').textContent = vt.words > 9999
      ? (vt.words / 1000).toFixed(1) + 'k' : vt.words;
    $('#zones').innerHTML =
      `<span>raw <b>${vt.raw}</b></span><span>wiki <b>${vt.wiki}</b></span>` +
      `<span>out <b>${vt.outputs}</b></span>`;
  }

  if (s.status) {
    const st = s.status;
    chip('#c-engine', `motor ${st.engine || '—'}`, st.engine_ok);
    chip('#c-stt', `stt ${st.stt || '—'}`, st.stt_ok);
    chip('#c-tts', `tts ${st.tts || '—'}`, st.tts_ok);
    if (st.ptt_key) $('#ptt-key').textContent = st.ptt_key.toUpperCase();
    if (st.tts) $('#a-out').textContent = st.tts;
  }

  if (s.agenda) renderAgenda(s.agenda);
  if (s.skills) renderSkills(s.skills);
  if (s.commands) renderCommands(s.commands);
  if (s.graph) { graphData = s.graph; drawGraph(); }
}

function ring(sel, pct) {
  if (pct == null) return;
  const el = $(sel);
  el.style.background = `conic-gradient(currentColor ${pct * 3.6}deg, #141c23 0deg)`;
  el.className = 'ring' + (pct > 85 ? ' hi' : pct > 65 ? ' mid' : '');
  el.querySelector('b').textContent = Math.round(pct);
}

function chip(sel, text, ok) {
  const el = $(sel);
  el.textContent = text;
  el.className = 'chip ' + (ok === undefined ? '' : ok ? 'on' : 'off');
}

function pulse(cls) { $('#pulse').className = 'dot ' + cls; }

/* ───────────── audio ───────────── */
function setLevel(l) {
  const pct = Math.min(100, l * 340);
  $('#a-level').style.width = pct + '%';
  wave.push(l);
  if (wave.length > 120) wave.shift();
  drawWave();
}

function drawWave() {
  const c = $('#wave'), ctx = c.getContext('2d');
  const w = c.width = c.offsetWidth * 2, h = c.height = 92;
  ctx.scale(1, 1); ctx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  ctx.strokeStyle = css.getPropertyValue('--hot').trim();
  ctx.lineWidth = 2; ctx.beginPath();
  wave.forEach((v, i) => {
    const x = i / Math.max(wave.length - 1, 1) * w;
    const y = h / 2 - Math.min(v * 6, 1) * (h / 2 - 4) * (i % 2 ? 1 : -1);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

/* ───────────── agenda ───────────── */
function renderAgenda(items) {
  $('#ag-count').textContent = items.length ? `${items.length}` : '';
  if (!items.length) { $('#agenda').innerHTML = '<p class="muted">horizonte despejado</p>'; return; }
  const now = Date.now() / 1000;
  $('#agenda').innerHTML = items.map(e => {
    const d = new Date(e.ts * 1000);
    const late = e.ts < now;
    const soon = !late && e.ts - now < 7200;
    return `<div class="ev ${late ? 'late' : soon ? 'now' : ''}">
      <time>${e.time || pad(d.getDate()) + '/' + pad(d.getMonth() + 1)}</time>
      <div class="t">${esc(e.title)}<span class="src">${esc(e.source || '')}</span></div>
    </div>`;
  }).join('');
}

/* ───────────── skills y comandos ───────────── */
function renderSkills(list) {
  $('#skills').innerHTML = list.map(s =>
    `<li data-skill="${esc(s.name)}"><b>${esc(s.name)}</b><span>${esc(s.description)}</span></li>`
  ).join('');
  document.querySelectorAll('#skills li').forEach(li =>
    li.onclick = () => submit(li.dataset.skill));
}

function fireSkill(name) {
  document.querySelectorAll('#skills li').forEach(li => {
    li.classList.toggle('fire', li.dataset.skill === name);
  });
}

function renderCommands(cmds) {
  $('#cmds').innerHTML = cmds.map(c =>
    `<li data-cmd="${esc(c.send)}"><b>${esc(c.key)}</b> ${esc(c.label)}</li>`).join('');
  document.querySelectorAll('#cmds li').forEach(li =>
    li.onclick = () => submit(li.dataset.cmd));
}

/* ───────────── grafo del vault ───────────── */
function drawGraph() {
  if (!graphData) return;
  const c = $('#graph'), ctx = c.getContext('2d');
  const w = c.width = c.offsetWidth * 2, h = c.height = c.offsetHeight * 2;
  ctx.clearRect(0, 0, w, h);
  const nodes = graphData.nodes.slice(0, 60);
  if (!nodes.length) return;

  const css = getComputedStyle(document.documentElement);
  const hot = css.getPropertyValue('--hot').trim();
  const cool = css.getPropertyValue('--cool').trim();

  const pos = {};
  nodes.forEach((n, i) => {
    const a = i / nodes.length * Math.PI * 2;
    const r = (0.24 + 0.62 * (1 - n.deg / (nodes[0].deg || 1))) * Math.min(w, h) * .45;
    pos[n.id] = { x: w / 2 + Math.cos(a) * r, y: h / 2 + Math.sin(a) * r, d: n.deg };
  });

  ctx.strokeStyle = 'rgba(95,118,134,.35)'; ctx.lineWidth = 1;
  (graphData.edges || []).forEach(e => {
    const a = pos[e.s], b = pos[e.t];
    if (!a || !b) return;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  });

  Object.values(pos).forEach(p => {
    const r = 2.4 + Math.min(p.d, 8) * 1.1;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7);
    ctx.fillStyle = p.d > 3 ? hot : cool;
    ctx.globalAlpha = p.d > 3 ? .95 : .55;
    ctx.fill(); ctx.globalAlpha = 1;
  });
}
window.addEventListener('resize', () => { drawGraph(); drawWave(); });

/* ───────────── markdown mínimo ───────────── */
function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function md(src) {
  let t = esc(src);
  const blocks = [];
  t = t.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, code) =>
    '@@BLOCK' + (blocks.push('<pre><code>' + code.trim() + '</code></pre>') - 1) + '@@');
  t = t.replace(/^######\s+(.*)$/gm, '<h3>$1</h3>')
       .replace(/^###\s+(.*)$/gm, '<h3>$1</h3>')
       .replace(/^##\s+(.*)$/gm, '<h2>$1</h2>')
       .replace(/^#\s+(.*)$/gm, '<h1>$1</h1>')
       .replace(/^---+$/gm, '<hr>')
       .replace(/^&gt;\s?(.*)$/gm, '<blockquote>$1</blockquote>')
       .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
                (_, a, b) => `<a class="wl" data-note="${a}">${b || a}</a>`)
       .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
       .replace(/`([^`]+)`/g, '<code>$1</code>')
       .replace(/^\s*[-*]\s+\[ \]\s+(.*)$/gm, '<li>☐ $1</li>')
       .replace(/^\s*[-*]\s+\[x\]\s+(.*)$/gmi, '<li>☑ $1</li>')
       .replace(/^\s*[-*]\s+(.*)$/gm, '<li>$1</li>')
       .replace(/^\s*\d+[.)]\s+(.*)$/gm, '<li>$1</li>');
  t = t.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>');
  t = t.split(/\n{2,}/).map(p =>
    /^\s*<(h\d|ul|pre|hr|blockquote|table)/.test(p) ? p : `<p>${p.replace(/\n/g, '<br>')}</p>`
  ).join('\n');
  t = t.replace(/@@BLOCK(\d+)@@/g, (_, i) => blocks[i]);
  return t;
}

function render(markdown) {
  const el = $('#out');
  el.innerHTML = md(markdown);
  el.scrollTop = 0;
  el.querySelectorAll('a.wl').forEach(a =>
    a.onclick = () => submit(`abre la nota ${a.dataset.note}`));
}

/* ───────────── log ───────────── */
const WHO = { you: 'tu', fri: 'friday', sys: 'sys', err: 'error' };
function log(kind, text) {
  if (!text) return;
  const d = new Date();
  const el = document.createElement('div');
  el.className = 'line ' + kind;
  el.innerHTML = `<time>${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}</time>` +
                 `<span class="who">${WHO[kind] || kind}</span>` +
                 `<span class="txt">${esc(text)}</span>`;
  const box = $('#log');
  box.appendChild(el);
  while (box.children.length > 220) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

/* ───────────── entrada de texto ───────────── */
$('#entry').onsubmit = e => {
  e.preventDefault();
  const v = $('#input').value.trim();
  if (v) { submit(v); $('#input').value = ''; }
};
function submit(text) { log('you', text); send('command', { text }); pulse('busy'); }

/* la barra es de FRIDAY, no del navegador */
window.addEventListener('keydown', e => {
  if (e.code === 'Space' && document.activeElement !== $('#input')) e.preventDefault();
});

/* ───────────── secuencia de arranque ───────────── */
function boot(s) {
  const st = s.status || {};
  const L = [
    ['F.R.I.D.A.Y OS', 'hl'],
    [`  motor .......... ${st.engine || '—'}`, st.engine_ok ? 'ok' : 'no'],
    [`  stt local ...... ${st.stt || '—'}`, st.stt_ok ? 'ok' : 'no'],
    [`  tts local ...... ${st.tts || '—'}`, st.tts_ok ? 'ok' : 'no'],
    [`  vault .......... ${(s.vault || {}).notes ?? 0} notas, ${(s.vault || {}).links ?? 0} enlaces`, 'ok'],
    [`  push to talk ... ${(st.ptt_key || 'space').toUpperCase()} (manten)`, 'ok'],
    ['', ''],
    ['  audio local. sin red. sin base de datos.', ''],
    ['  todo cae en markdown enlazado.', ''],
    ['', ''],
    ['  Manten la barra y habla, Boss.', 'hl'],
  ];
  $('#out').innerHTML = `<div class="boot">${L.map(([t, c]) =>
    c ? `<span class="${c}">${esc(t)}</span>` : esc(t)).join('\n')}</div>`;
}

connect();
