/* ─────────────────────────────────────────────
   汉字的一生 · 前端逻辑
   · 单一入口 index.json + 按码位分片的字形数据
   · 五阶段切换做「墨迹描画 + 交叠淡出」动画
   ───────────────────────────────────────────── */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]/;

  const state = {
    index: null,          // index.json
    shards: new Map(),    // bucket -> Promise<data>
    char: null,           // 当前字
    rec: null,             // 当前字的记录
    stage: 0,             // 当前阶段序号
    playing: false,
    playTimer: 0,
    front: 'A',           // 当前用于显示描画的图层
    libShown: 0,
    libPool: [],
  };

  const QUICK = ['日', '月', '水', '山', '人', '馬', '龍', '學', '花', '雨', '心', '木'];
  const STAMP = ['甲骨', '金文', '小篆', '隶书', '楷书'];
  const STAGE_KEYS = ['o', 'b', 's', 'l', 'k'];
  // 来源族 -> 准确的书体名（避免把简帛、大篆笼统说成隶书、小篆）
  const FAMILY_LABEL = {
    silk: '简帛', hanjian: '汉简', clerical: '隶书', 'clerical-han': '汉隶',
    bigseal: '大篆', seal: '小篆', oracle: '甲骨', bronze: '金文',
  };

  function familyOf(rec, key) {
    const src = rec && rec.src ? rec.src[key] : null;
    if (!src) return null;
    const stem = src.replace(/^[^-]+-/, '');
    return stem.split('-')[0];
  }

  function stageName(rec, idx) {
    const base = state.index.stages[idx].name;
    const fam = familyOf(rec, STAGE_KEYS[idx]);
    const label = fam && FAMILY_LABEL[fam];
    if (!label) return base;
    if (idx === 2 && fam === 'bigseal') return '大篆';
    if (idx === 3 && (fam === 'silk' || fam === 'hanjian')) return `隶书 · ${label}`;
    return base;
  }

  /* ── 工具 ── */
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function toast(msg, ms = 1900) {
    let el = document.querySelector('.toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.remove('err');
    requestAnimationFrame(() => el.classList.add('on'));
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('on'), ms);
  }

  const fmtNum = (n) => (n >= 10000 ? (n / 10000).toFixed(1) + ' 万' : String(n));

  /* ── 数据加载 ── */
  async function loadIndex() {
    const res = await fetch('data/index.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error('index ' + res.status);
    state.index = await res.json();
    state.ancientChars = state.index.ancientChars || '';
    state.ancient = new Set(state.ancientChars);
    state.quad = new Set(state.index.quadChars || '');
    state.oracleChars = state.index.oracleChars || '';
    state.oracleOnly = new Set(state.oracleChars);
  }

  function bucketOf(ch) {
    return ch.codePointAt(0) % state.index.buckets;
  }

  function loadShard(b) {
    if (state.shards.has(b)) return state.shards.get(b);
    const p = fetch(`data/g/${b}.json?v=${state.index.version}`, { cache: 'force-cache' })
      .then((r) => (r.ok ? r.json() : {}))
      .catch(() => ({}));
    state.shards.set(b, p);
    return p;
  }

  async function lookup(ch) {
    if (!state.index.chars.includes(ch)) return null;
    const data = await loadShard(bucketOf(ch));
    return data[ch] || null;
  }

  /* 预取相邻字所在分片，让「随机看字」不卡 */
  function prefetch(chars) {
    const seen = new Set();
    for (const ch of chars) {
      const b = bucketOf(ch);
      if (seen.has(b)) continue;
      seen.add(b);
      loadShard(b);
    }
  }

  /* ── 时间轴（五体字形卡片） ── */
  function buildTimeline() {
    const ol = $('tlItems');
    ol.innerHTML = '';
    state.index.stages.forEach((st, i) => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tl-btn';
      btn.setAttribute('role', 'tab');
      btn.dataset.i = i;
      btn.innerHTML = `
        <span class="tl-thumb">
          <span class="tl-idx">${String(i + 1).padStart(2, '0')}</span>
          <svg viewBox="0 0 1000 1000" aria-hidden="true"><path d=""/></svg>
          <span class="tl-missing" hidden>${'字'}</span>
        </span>
        <span class="tl-txt">
          <span class="tl-name">${st.name}</span>
          <span class="tl-era">${st.era}</span>
        </span>`;
      btn.addEventListener('click', () => {
        stopPlay();
        goStage(i);
      });
      li.appendChild(btn);
      ol.appendChild(li);
    });
  }

  function syncTimeline() {
    const btns = [...document.querySelectorAll('.tl-btn')];
    btns.forEach((b, i) => {
      const key = STAGE_KEYS[i];
      const has = !!(state.rec && (key === 'k' ? state.rec.k : state.rec[key]));
      b.setAttribute('aria-selected', i === state.stage ? 'true' : 'false');
      b.classList.toggle('passed', i < state.stage && has);
      b.classList.toggle('na', !has);
      b.title = has ? stageName(state.rec, i) : '此期未见传世字形';
      const nameEl = b.querySelector('.tl-name');
      if (nameEl) nameEl.textContent = has ? stageName(state.rec, i) : state.index.stages[i].name;
      const path = b.querySelector('.tl-thumb svg path');
      const missing = b.querySelector('.tl-missing');
      if (has) {
        path.setAttribute('d', key === 'k' ? state.rec.k : state.rec[key]);
        path.parentNode.style.display = '';
        missing.hidden = true;
      } else {
        path.setAttribute('d', '');
        path.parentNode.style.display = 'none';
        missing.hidden = false;
        missing.textContent = state.char || '';
      }
    });
  }

  function glyphFor(stageIdx) {
    if (!state.rec) return null;
    const key = STAGE_KEYS[stageIdx];
    if (key === 'k') return state.rec.k || null;
    return state.rec[key] || null;
  }

  /* ── 字形渲染（双图层交叠 + 墨迹描画） ── */
  function setPath(layerId, d) {
    const p = $('path' + layerId);
    if (!d) {
      p.setAttribute('d', '');
      return;
    }
    p.setAttribute('d', d);
  }

  function stopAnims(el) {
    if (!el) return;
    el.getAnimations().forEach((a) => a.cancel());
  }

  function drawGlyph(stageIdx, opts = {}) {
    const d = glyphFor(stageIdx);
    const frame = $('glyphFrame');
    const empty = $('glyphEmpty');
    const svg = $('glyph');
    const stage = state.index.stages[stageIdx];

    frame.dataset.era = String(stageIdx);
    $('glyphEra').textContent = stage.era;

    if (!d) {
      setPath('A', '');
      setPath('B', '');
      empty.hidden = false;
      $('glyphEmptyChar').textContent = state.char || '字';
      frame.classList.add('clean');
      svg.style.opacity = '0';
      $('glyphStamp').classList.remove('on');
      $('glyphCaption').innerHTML =
        `<span class="cap-l">${stage.name} · ${stage.era}</span>` +
        `<span class="cap-r">${stageIdx + 1} / ${state.index.stages.length}</span>`;
      renderPips(stageIdx);
      return;
    }

    empty.hidden = true;
    svg.style.opacity = '1';
    frame.classList.remove('clean');

    const back = state.front === 'A' ? 'B' : 'A';
    const prev = state.front;
    const path = $('path' + back);
    const oldPath = $('path' + prev);

    setPath(back, d);
    stopAnims(path);

    /* 旧字淡出并轻微上浮 */
    if (oldPath.getAttribute('d')) {
      stopAnims(oldPath);
      oldPath.animate(
        [
          { opacity: 1, transform: 'none' },
          { opacity: 0, transform: 'translateY(-1.4%) scale(1.012)' },
        ],
        { duration: 420, easing: 'cubic-bezier(.4,.14,.16,1)', fill: 'forwards' },
      ).onfinish = () => {
        if (state.front !== prev) return;
        oldPath.setAttribute('d', '');
        oldPath.style.opacity = '';
      };
    }

    /* 新字：先描边成笔，再填墨 */
    const reduced = reduceMotion() || opts.instant;
    state.front = back;

    if (reduced) {
      path.style.opacity = '1';
      prev !== back && $('path' + prev).setAttribute('d', '');
      renderPips(stageIdx);
    } else {
      let len = 1200;
      try { len = Math.max(300, path.getTotalLength()); } catch (e) { /* noop */ }
      const dur = Math.min(1650, Math.max(720, 520 + len * 0.42));
      path.style.strokeDasharray = String(len);
      path.style.fillOpacity = '0';
      path.style.opacity = '1';
      path.animate(
        [
          { strokeDashoffset: len, fillOpacity: 0, strokeOpacity: 1, strokeWidth: 9, offset: 0 },
          { strokeDashoffset: 0, fillOpacity: 0, strokeOpacity: 1, strokeWidth: 9, offset: 0.58 },
          { strokeDashoffset: 0, fillOpacity: 0.35, strokeOpacity: 1, strokeWidth: 9, offset: 0.78 },
          { strokeDashoffset: 0, fillOpacity: 1, strokeOpacity: 0, strokeWidth: 9, offset: 1 },
        ],
        { duration: dur, easing: 'cubic-bezier(.4,.14,.16,1)', fill: 'forwards' },
      );
    }

    $('glyphStamp').classList.toggle('on', stageIdx !== 4);
    $('glyphCaption').innerHTML =
      `<span class="cap-l">${stageName(state.rec, stageIdx)} · ${stage.era}</span>` +
      `<span class="cap-r">${stageIdx + 1} / ${state.index.stages.length}</span>`;
    renderPips(stageIdx);
  }

  function renderPips(cur) {
    if (!state.rec) return;
    $('glyphPips').innerHTML = STAGE_KEYS.map((k, i) => {
      const has = !!(k === 'k' ? state.rec.k : state.rec[k]);
      const cls = i === cur ? 'cur' : has ? 'on' : '';
      return `<i class="${cls}"></i>`;
    }).join('');
  }

  /* ── 阶段切换 ── */
  function goStage(i, opts = {}) {
    const n = state.index.stages.length;
    state.stage = Math.max(0, Math.min(n - 1, i));
    drawGlyph(state.stage, opts);
    syncTimeline();
    renderInfo(state.stage);
  }

  function stepStage(dir) {
    stopPlay();
    const n = state.index.stages.length;
    let i = state.stage + dir;
    if (i < 0) i = 0;
    if (i > n - 1) i = n - 1;
    if (i !== state.stage) goStage(i);
  }

  /* ── 右侧信息 ── */
  function renderInfo(i) {
    const s = state.index.stages[i];
    const rec = state.rec;
    $('noteName').textContent = stageName(rec, i);
    $('noteSpan').textContent = s.span;
    $('noteBody').textContent = s.note;

    const has = !!(rec && (STAGE_KEYS[i] === 'k' ? rec.k : rec[STAGE_KEYS[i]]));
    const src = rec && rec.src ? rec.src[STAGE_KEYS[i]] : null;
    const box = $('source');
    if (src) {
      const url = 'https://commons.wikimedia.org/wiki/File:' + encodeURIComponent(src + '.svg');
      box.innerHTML = `字形来源：<a href="${url}" target="_blank" rel="noopener">${src}.svg</a> · 公有领域`;
    } else if (i === 4) {
      box.innerHTML = '今文字形由霞鹜文楷轮廓转曲 · SIL OFL 1.1';
    } else {
      box.innerHTML = has ? '' : '此期尚未见可靠字形，此处留白。';
    }
  }

  function renderChar(ch) {
    const rec = state.rec || {};
    $('charBig').textContent = ch;
    $('charPinyin').textContent = rec.p || '';
    $('charPinyin').style.display = rec.p ? '' : 'none';

    const facts = [];
    if (rec.st) facts.push(`${rec.st} 画`);
    if (rec.rd) facts.push(`部首 ${rec.rd}`);
    $('charFacts').innerHTML = facts.map((f) => `<span>${f}</span>`).join('');

    const present = STAGE_KEYS.filter((k) => (k === 'k' ? rec.k : rec[k])).length;
    const cp = ch.codePointAt(0).toString(16).toUpperCase();
    const rows = [
      ['Unicode', `U+${cp}`],
      ['五体可考', `<b>${present}</b><span class="dim"> / 5</span>`],
      ['普通字序', rec.lvl ? `${rec.lvl}` : '<span class="dim">—</span>'],
    ];
    $('dossier').innerHTML = rows
      .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
      .join('');

    const def = rec.df ? rec.df.replace(/^\(.*?\)\s*/, '') : '';
    $('charDef').textContent = def || '';

    document.title = `${ch}的一生 · 从甲骨文到楷书`;
  }

  /* ── 主流程：选字 ── */
  async function showChar(ch, push = true) {
    ch = (ch || '').trim();
    const m = ch.match(CJK);
    if (!m) return false;
    ch = m[0];

    stopPlay();
    const frame = $('glyphFrame');
    $('glyphLoader').classList.add('on');

    let rec = await lookup(ch);
    $('glyphLoader').classList.remove('on');

    if (!rec) {
      toast(`「${ch}」暂未收录 · 目前收录 9500+ 常用汉字`, 2400);
      return false;
    }

    state.char = ch;
    state.rec = rec;
    $('q').value = ch;
    $('clear').hidden = false;
    $('stage').hidden = false;
    $('stage').classList.remove('enter');
    void $('stage').offsetWidth;
    $('stage').classList.add('enter');

    renderChar(ch);

    // 首屏选一个有字形的阶段：优先甲骨，否则第一个可用
    let start = 0;
    if (!glyphFor(0)) {
      start = STAGE_KEYS.findIndex((k) => (k === 'k' ? rec.k : rec[k]));
      if (start < 0) start = 0;
    }
    state.front = 'A';
    setPath('A', ''); setPath('B', '');
    goStage(start, { instant: false });

    if (push) {
      const url = new URL(location.href);
      url.searchParams.set('z', ch);
      history.replaceState(null, '', url);
    }

    // 预取同分片相邻字的分片
    const idx = state.index.chars.indexOf(ch);
    if (idx >= 0) prefetch(state.index.chars.slice(Math.max(0, idx - 12), idx + 13));

    // 滚动到舞台（若在首屏外）
    const rect = $('stage').getBoundingClientRect();
    if (rect.top > window.innerHeight * 0.55) {
      $('stage').scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' });
    }
    return true;
  }

  /* ── 自动演进 ── */
  function availableStages() {
    if (!state.rec) return [];
    return STAGE_KEYS.map((k, i) => {
      const has = k === 'k' ? !!state.rec.k : !!state.rec[k];
      return has ? i : -1;
    }).filter((i) => i >= 0);
  }

  function startPlay() {
    if (state.playing) return;
    const list = availableStages();
    if (list.length < 2) {
      toast('此字可考字形不足两体，暂无演变可看');
      return;
    }
    state.playing = true;
    $('play').classList.add('playing');
    setPlayLabel('暂停');

    let pos = list.indexOf(state.stage);
    if (pos < 0 || pos >= list.length - 1) {
      goStage(list[0], { instant: true });
      pos = 0;
    }

    const tick = () => {
      if (!state.playing) return;
      pos += 1;
      if (pos >= list.length) {
        stopPlay();
        return;
      }
      goStage(list[pos]);
      state.playTimer = setTimeout(tick, 1800);
    };
    state.playTimer = setTimeout(tick, 1500);
  }

  function stopPlay() {
    state.playing = false;
    clearTimeout(state.playTimer);
    const btn = $('play');
    if (btn) {
      btn.classList.remove('playing');
      setPlayLabel('自动演进');
    }
  }

  function setPlayLabel(text) {
    const btn = $('play');
    if (!btn) return;
    const span = btn.querySelector('.btn-label');
    if (span) span.textContent = text;
  }

  function togglePlay() {
    state.playing ? stopPlay() : startPlay();
  }

  /* ── 随机一字 ── */
  function randomChar() {
    const pool = state.ancientChars && state.ancientChars.length
      ? state.ancientChars
      : state.index.chars.split('');
    let ch = state.char;
    for (let i = 0; i < 30 && ch === state.char; i++) {
      ch = pool[Math.floor(Math.random() * pool.length)];
    }
    showChar(ch);
  }

  /* ── 字源库 ── */
  const LIB_FILTERS = {
    all: () => true,
    quad: (ch) => state.quad.has(ch),
    oracle: (ch) => state.oracleOnly.has(ch),
    full: (ch) => !state.ancient.has(ch),
  };

  function buildLibrary() {
    const all = state.index.chars.split('');
    state.libPool = all;
    state.libFilter = 'all';

    // 计数
    const counts = {
      all: all.length,
      quad: state.quad.size,
      oracle: state.oracleOnly.size,
      full: all.length - state.ancient.size,
    };
    document.querySelectorAll('#libFilters .chip').forEach((btn) => {
      const f = btn.dataset.filter;
      btn.innerHTML = `${btn.textContent.replace(/\s*\d+$/, '')}<span class="n">${counts[f] || 0}</span>`;
      btn.classList.toggle('on', f === 'all');
    });

    $('libFilters').addEventListener('click', (e) => {
      const btn = e.target.closest('.chip');
      if (!btn) return;
      const f = btn.dataset.filter;
      if (!LIB_FILTERS[f] || f === state.libFilter) return;
      state.libFilter = f;
      document.querySelectorAll('#libFilters .chip').forEach((b) => b.classList.toggle('on', b === btn));
      applyFilter();
    });

    applyFilter();
  }

  function applyFilter() {
    const pred = LIB_FILTERS[state.libFilter] || (() => true);
    state.libPool = state.index.chars.split('').filter(pred);
    state.libShown = 0;
    $('library').innerHTML = '';
    showMoreChars(180);
  }

  function showMoreChars(n) {
    const lib = $('library');
    const frag = document.createDocumentFragment();
    const end = Math.min(state.libPool.length, state.libShown + n);
    for (let i = state.libShown; i < end; i++) {
      const ch = state.libPool[i];
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'lib-cell';
      cell.dataset.ch = ch;
      cell.innerHTML = `<span>${ch}</span><i></i>`;
      if (state.ancient.has(ch)) cell.classList.add('has-ancient');
      cell.title = `看「${ch}」的演变`;
      frag.appendChild(cell);
    }
    lib.appendChild(frag);
    state.libShown = end;
    const more = $('libMore');
    more.hidden = state.libShown >= state.libPool.length;
    more.textContent = `再载入一批（已显示 ${state.libShown} / ${state.libPool.length}）`;
  }

  /* ── 分享 ── */
  async function copyLink() {
    const url = new URL(location.href);
    if (state.char) url.searchParams.set('z', state.char);
    try {
      await navigator.clipboard.writeText(url.toString());
      toast('链接已复制');
    } catch (e) {
      // 退化：选中地址栏内容提示
      const ta = document.createElement('textarea');
      ta.value = url.toString();
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        toast('链接已复制');
      } catch (err) {
        toast('复制失败，请手动复制地址栏');
      }
      ta.remove();
    }
  }

  /* ── 事件绑定 ── */
  function bind() {
    $('search').addEventListener('submit', (e) => {
      e.preventDefault();
      showChar($('q').value);
    });
    $('q').addEventListener('input', (e) => {
      const v = e.target.value;
      $('clear').hidden = !v;
      const m = v.match(CJK);
      // 输入一个汉字就即时预览
      if (m && v.length === 1) {
        showChar(m[0]);
      }
    });
    $('q').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        showChar($('q').value);
      }
    });
    $('clear').addEventListener('click', () => {
      $('q').value = '';
      $('clear').hidden = true;
      $('q').focus();
    });

    $('randomBtn').addEventListener('click', randomChar);
    $('play').addEventListener('click', togglePlay);
    $('stepBack').addEventListener('click', () => stepStage(-1));
    $('stepFwd').addEventListener('click', () => stepStage(1));
    $('copy').addEventListener('click', copyLink);

    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowLeft') { stepStage(-1); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { stepStage(1); e.preventDefault(); }
      else if (e.key === ' ' && state.char) { togglePlay(); e.preventDefault(); }
    });

    $('library').addEventListener('click', (e) => {
      const cell = e.target.closest('.lib-cell');
      if (cell) showChar(cell.dataset.ch);
    });

    $('quick').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) showChar(b.dataset.ch);
    });

    // 顶栏滚动态
    const top = document.querySelector('.top');
    const onScroll = () => top.classList.toggle('scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    // 出场动画
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (en.isIntersecting) {
          en.target.classList.add('in');
          io.unobserve(en.target);
        }
      }
    }, { rootMargin: '0px 0px -8% 0px' });
    document.querySelectorAll('.reveal').forEach((el) => io.observe(el));
  }

  /* ── 启动 ── */
  async function boot() {
    bind();
    $('year').textContent = new Date().getFullYear();

    try {
      await loadIndex();
    } catch (e) {
      $('hint').textContent = '数据加载失败：请用本地服务器打开（file:// 下浏览器禁止读取数据文件）。';
      return;
    }

    const n = state.index.count;
    const a = state.index.ancient;
    $('stat-count').textContent = fmtNum(n);
    $('stat-ancient').textContent = fmtNum(a);
    $('stat-count2').textContent = fmtNum(n);
    $('stat-ancient2').textContent = fmtNum(a);

    // 推荐字：只留真收录的
    const quick = $('quick');
    quick.innerHTML = '<span class="quick-label">试试</span>';
    const picks = QUICK.filter((c) => state.index.chars.includes(c));
    const quadList = (state.index.quadChars || '').split('');
    const quadPicked = [];
    for (const ch of quadList) {
      if (quadPicked.length >= 4) break;
      if (!QUICK.includes(ch) && picks.length < 8) quadPicked.push(ch);
    }
    const extra = state.index.chars.split('').filter((c) => !QUICK.includes(c));
    while (picks.length < 12 && extra.length) {
      const c = extra.shift();
      if (state.index.chars.includes(c)) picks.push(c);
    }
    for (const ch of [...picks, ...quadPicked].slice(0, 12)) {
      const b = document.createElement('button');
      b.type = 'button';
      b.dataset.ch = ch;
      b.textContent = ch;
      quick.appendChild(b);
    }
    prefetch(picks);

    buildTimeline();
    buildLibrary();

    // 深链
    const url = new URL(location.href);
    const fromUrl = url.searchParams.get('z') || decodeURIComponent(location.hash.slice(1));
    if (fromUrl && CJK.test(fromUrl)) {
      await showChar(fromUrl, false);
    } else {
      // 首屏随机给一个默认字
      const seed = picks[0];
      if (seed) $('q').placeholder = `输入任意汉字，如 ${seed} 水 馬 學`;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
