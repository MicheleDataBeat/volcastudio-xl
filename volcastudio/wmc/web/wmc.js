/* VolcaStudio XL Browser App — browser interface.
   The page holds no musical logic: every transformation, plan, encoding and
   transfer is computed by the local helper (the same backend as the
   Desktop App). This file renders state, gathers choices and asks for consent. */
'use strict';
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'text') el.textContent = value;
      else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
      else if (key === 'dataset') Object.assign(el.dataset, value);
      else if (key === 'style') Object.assign(el.style, value);  // CSSOM: allowed by the CSP
      else if (value === true) el.setAttribute(key, '');
      else el.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  const fmt = {
    s: (value) => (value || 0).toFixed(2),
    shift: (value) => (value > 0 ? '+' : value < 0 ? '−' : '±') + Math.abs(value || 0),
    bytes: (value) => value > 1048576 ? (value / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(value / 1024)) + ' kB',
    time: () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    slot: (n) => String(n).padStart(2, '0'),
  };

  // ------------------------------------------------------------------ session
  const session = (() => {
    const params = new URLSearchParams(location.hash.slice(1));
    const token = params.get('k');
    const code = params.get('c');
    if (token) sessionStorage.setItem('wmc-token', token);
    if (params.get('browser')) sessionStorage.setItem('wmc-browser', params.get('browser'));
    if (token || code) history.replaceState(null, '', location.pathname);
    return { token: sessionStorage.getItem('wmc-token'), code, browser: sessionStorage.getItem('wmc-browser'), closed: false };
  })();

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function api(method, path, body, extra = {}) {
    if (session.closed) throw new ApiError(0, 'The Browser App is closed. Open VolcaStudio XL Browser App again.');
    const headers = { 'X-WMC-Token': session.token || '' };
    let payload = body;
    if (body !== undefined && !(body instanceof Blob) && !(body instanceof ArrayBuffer)) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    Object.assign(headers, extra.headers || {});
    let response;
    try {
      response = await fetch(path, { method, headers, body: payload, cache: 'no-store' });
    } catch (error) {
      sessionLost('The Browser App’s helper is not answering. If you closed it, open VolcaStudio XL Browser App again.');
      throw new ApiError(0, 'The Browser App helper is not answering.');
    }
    if (response.status === 401) {
      sessionLost('This window belongs to a closed Browser App session. Open VolcaStudio XL Browser App again; it reopens this page.');
      throw new ApiError(401, 'Session closed.');
    }
    if (extra.raw) {
      if (!response.ok) throw new ApiError(response.status, (await response.json().catch(() => ({}))).error || 'Request failed');
      return response;
    }
    const type = response.headers.get('Content-Type') || '';
    const data = type.startsWith('application/json') ? await response.json() : null;
    if (!response.ok) throw new ApiError(response.status, (data && data.error) || 'Request failed.');
    return data;
  }
  const get = (path) => api('GET', path);
  const post = (path, body = {}) => api('POST', path, body);
  const put = (path, body = {}) => api('PUT', path, body);
  const q = encodeURIComponent;

  function sessionLost(message) {
    const notice = $('#session-notice');
    notice.textContent = message;
    notice.hidden = false;
  }

  // ------------------------------------------------------------------ minutes
  function minute(text, kind = '') {
    const list = $('#minutes-list');
    list.append(h('li', { class: kind }, `${fmt.time()}  ${text}`));
    while (list.children.length > 300) list.firstChild.remove();
    list.scrollTop = list.scrollHeight;
    $('#minutes-last').textContent = text.length > 120 ? text.slice(0, 117) + '…' : text;
    $('#announcer').textContent = text;
  }
  const fail = (error) => minute(error instanceof Error ? error.message : String(error), 'error');
  async function attempt(fn) {
    try { return await fn(); } catch (error) { if (!(error instanceof ApiError && error.status === 401)) { fail(error); await notify('Not done', error.message); } return undefined; }
  }

  // ------------------------------------------------------------------ pixels
  const PIXELS = {
    emblem: [
      '......kkkk......', '....kkkk..kk....', '...kkkkk....k...', '..kkkkkk.....k..',
      '.kkkkkkk......k.', '.kkkkkkk......k.', 'kkkkkkkr.......k', 'kkkkkkrrr......k',
      'kkkkkkkr.......k', 'kkkkkkkk.......k', '.kkkkkkk......k.', '.kkkkkkk......k.',
      '..kkkkkk.....k..', '...kkkkk....k...', '....kkkk..kk....', '......kkkk......'],
    spark: [
      '....r.....', '....r.....', '..g.r.g...', '...grg....', 'rrrrgrrrr.',
      '...grg....', '..g.r.g...', '....r.....', '....r.....', '..........'],
  };
  function pixel(name) {
    const rows = PIXELS[name];
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${rows[0].length} ${rows.length}`);
    svg.setAttribute('class', 'pixel');
    const classes = { k: 'ink', r: 'red', g: 'gold', p: 'paper' };
    rows.forEach((row, y) => [...row].forEach((c, x) => {
      if (!classes[c]) return;
      const rect = document.createElementNS(ns, 'rect');
      Object.entries({ x, y, width: 1, height: 1, class: classes[c] }).forEach(([k, v]) => rect.setAttribute(k, v));
      svg.append(rect);
    }));
    return svg;
  }

  // ------------------------------------------------------------------ motion & celebrations
  const motion = {
    get on() {
      try { const saved = localStorage.getItem('wmc-motion'); if (saved !== null) return saved === 'on'; } catch (e) { /* storage blocked */ }
      return !matchMedia('(prefers-reduced-motion: reduce)').matches;
    },
    set(value) {
      try { localStorage.setItem('wmc-motion', value ? 'on' : 'off'); } catch (e) { /* storage blocked */ }
      document.body.classList.toggle('motion', value);
    },
  };
  const CELEBRATIONS = {
    saved: ['Kit saved.', 'Sample copies and tuning metadata are saved on this computer.'],
    refined95: ['95% sample memory.', 'Review the kit’s remaining time before adding samples.'],
    refined99: ['99% sample memory.', 'The saved kit is close to the 65-second limit.'],
    memory100: ['Sample memory full.', 'The kit uses the 65-second sample budget.'],
    slots100: ['100 sample slots.', 'The kit uses every sample slot.'],
    capacity: ['Kit at capacity.', 'All 100 slots and the sample memory budget are used.'],
    aligned: ['Pitch alignment applied.', 'Listen to the result and save the kit when ready.'],
    groove: ['Groove bank saved.', 'The bank is saved on this computer. Sending is a separate step.'],
    backup: ['Pattern backup saved.', 'Ten memories and the current snapshot passed their frame checks.'],
    restored: ['Kit restored.', 'The archived kit is available again.'],
    sent: ['Signals sent.', 'Check the result on the Volca.'],
  };
  let celebrationTimer = null;
  function celebrate(key) {
    const [title, text] = CELEBRATIONS[key] || CELEBRATIONS.saved;
    $('#celebration-title').textContent = title;
    $('#celebration-text').textContent = text;
    const card = $('#celebration');
    card.hidden = true;
    void card.offsetWidth;
    card.hidden = false;
    clearTimeout(celebrationTimer);
    celebrationTimer = setTimeout(() => { card.hidden = true; }, 5000);
  }

  // ------------------------------------------------------------------ dialogs
  function ask({ title, body, actions, wide = false }) {
    const dialog = $('#dialog');
    $('#dialog-title').textContent = title;
    const content = $('#dialog-body');
    content.replaceChildren(...(Array.isArray(body) ? body : [body]).filter(Boolean).map((b) => (b instanceof Node ? b : h('p', {}, b))));
    const row = $('#dialog-actions');
    row.replaceChildren();
    let focus = null;
    for (const action of actions) {
      const button = h('button', { type: 'submit', value: action.value, class: action.kind || '' }, action.label);
      if (action.default) focus = button;
      row.append(button);
    }
    dialog.classList.toggle('wide', wide);
    return new Promise((resolve) => {
      dialog.returnValue = '';
      dialog.addEventListener('close', () => resolve(dialog.returnValue), { once: true });
      dialog.showModal();
      (focus || row.firstChild).focus();
    });
  }
  const notify = (title, text) => ask({ title, body: text, actions: [{ label: 'OK', value: 'ok', default: true }] });

  function promptText({ title, text, label, value = '', placeholder = '', pattern, confirm = 'OK' }) {
    const input = h('input', { type: 'text', value, placeholder, spellcheck: 'false', autocomplete: 'off', 'aria-label': label });
    const dialog = $('#dialog');
    const result = ask({ title, body: [text && h('p', {}, text), h('label', {}, label, input)], actions: [
      { label: 'Cancel', value: '' }, { label: confirm, value: 'ok', kind: 'primary' }] });
    setTimeout(() => { input.focus(); input.select(); }, 0);
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); dialog.close('ok'); } });
    return result.then((answer) => {
      if (answer !== 'ok') return null;
      const text = input.value.trim();
      if (pattern && !pattern.test(text)) { notify('Check the value', 'That value is not valid here.'); return null; }
      return text;
    });
  }

  function semitonePrompt(direction, count) {
    const input = h('input', { type: 'text', class: 'digits', inputmode: 'numeric', maxlength: '2', placeholder: '07', 'aria-label': 'Semitones, zero to ninety-nine' });
    const dialog = $('#dialog');
    const body = [
      h('p', {}, `${direction < 0 ? 'Lower' : 'Raise'} ${count} selected sample${count === 1 ? '' : 's'} by how many semitones?`),
      h('p', { class: 'hint' }, 'Type 0–99 (one or two digits). Pitch and duration change together, like tape. Originals stay intact; the marker adds up.'),
      input,
    ];
    const result = ask({ title: direction < 0 ? 'Varispeed · lower pitch' : 'Varispeed · raise pitch', body, actions: [
      { label: 'Cancel', value: '' }, { label: 'Apply', value: 'ok', kind: 'primary' }] });
    setTimeout(() => input.focus(), 0);
    input.addEventListener('input', () => { input.value = input.value.replace(/\D/g, '').slice(0, 2); });
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); dialog.close('ok'); } });
    return result.then((answer) => (answer === 'ok' && /^\d{1,2}$/.test(input.value) ? direction * parseInt(input.value, 10) : null));
  }

  // ------------------------------------------------------------------ operation strip & jobs
  const operation = {
    cancel: null,
    show(title, message = '', cancel = null) {
      $('#operation').hidden = false;
      $('#operation-title').textContent = title;
      $('#operation-message').textContent = message;
      this.cancel = cancel;
      $('#operation-cancel').disabled = !cancel;
      this.progress(0, 0);
    },
    message(text) { $('#operation-message').textContent = text; },
    progress(current, total) {
      const bar = $('#operation-bar');
      $('#operation').classList.toggle('indeterminate', !total);
      bar.style.width = total ? `${Math.min(100, (100 * current) / total)}%` : '0';
    },
    hide() { $('#operation').hidden = true; this.cancel = null; },
  };
  $('#operation-cancel').addEventListener('click', () => { if (operation.cancel) operation.cancel(); });

  const jobs = { active: null };

  function confirmBody(job) {
    const m = job.manifest || {};
    const output = S.devices && S.devices.outputs.find((d) => d.key === S.devices.selected.output);
    const where = h('p', {}, 'Output: ', h('strong', {}, output ? `${output.name} · ${output.api}` : 'chosen output'), ' → Volca SYNC IN. Pause other audio first.');
    const oneWay = h('p', { class: 'hint' }, 'Audio transfer is one-way: the Browser App can report that signals were sent, never that the Volca received them.');
    if (job.kind === 'kit') {
      return { title: 'Clear the Volca and load this kit?', confirm: 'Clear & send', body: [
        h('p', { class: 'warning' }, `All 100 sample slots will be cleared, then ${m.count} sample${m.count === 1 ? '' : 's'} (${fmt.s(m.seconds)} s) will be loaded in order.`),
        h('p', {}, `Prepared offline: ${m.count} upload signals + 100 clear signals, all verified.`), where, oneWay] };
    }
    if (job.kind === 'firmware') {
      return { title: 'Update the Volca firmware?', confirm: 'Send firmware signal', body: [
        h('p', { class: 'warning' }, `${m.name || 'Firmware'} ${m.version || ''} will replace the Volca's operating system.${m.experimental ? ' This release is experimental.' : ''}`),
        h('ol', {}, (m.procedure || []).map((step) => h('li', {}, step))), where, oneWay] };
    }
    const slots = (m.slots || []).map((n) => n + 1).join(', ');
    const notes = [];
    if (m.opaque_slots && m.opaque_slots.length) notes.push(h('p', { class: 'hint' }, `Uninitialized memories ${m.opaque_slots.map((n) => n + 1).join(', ')} are restored byte for byte; the Volca opens them with native defaults.`));
    if (m.current_edit_buffer_saved_not_restored) notes.push(h('p', { class: 'hint' }, 'The extra current snapshot stays in the file; it is not written to a memory.'));
    if (m.current_buffer_reset_requested) notes.push(h('p', { class: 'hint' }, 'After the memories, the current edit buffer is reset through MIDI IN.'));
    return { title: 'Replace these pattern memories?', confirm: 'Replace memories', body: [
      h('p', { class: 'warning' }, `Pattern memories ${slots} will be replaced. Sample audio and GLOBAL settings are untouched. Later edits made on the Volca and absent from this copy will be lost.`),
      ...notes, where, oneWay] };
  }

  const AFTER = {
    kit: 'Check a few slots on the Volca.',
    patterns: 'Select a restored memory on the Volca to check it.',
    grooves: 'Select a restored memory on the Volca to check it.',
    firmware: 'Wait for “End” on the Volca display, then restart it and check the version (power on holding REC).',
  };

  function runJob(start, { onDone, quietSuccess = false } = {}) {
    stopListening();
    return new Promise((resolve) => {
      start.then((job) => {
        jobs.active = job.id;
        operation.show(job.title, job.message, () => post('/api/job/cancel', { id: job.id }).catch(fail));
        minute(`${job.title}: started.`);
        let confirming = false;
        const poll = async () => {
          let current;
          try { current = (await get('/api/job')).job; } catch (error) { operation.hide(); resolve(null); return; }
          if (!current || current.id !== job.id) { operation.hide(); resolve(null); return; }
          operation.message(current.message + (current.cancel_requested ? ' · cancelling…' : ''));
          operation.progress(current.current, current.total);
          if (current.state === 'confirm' && !confirming) {
            confirming = true;
            const view = confirmBody(current);
            const answer = await ask({ title: view.title, body: view.body, wide: current.kind === 'firmware', actions: [
              { label: 'Cancel — keep the Volca as it is', value: 'no', default: true }, { label: view.confirm, value: 'yes', kind: 'send' }] });
            await post('/api/job/answer', { id: current.id, approve: answer === 'yes' }).catch(fail);
          }
          if (current.state === 'finished') {
            jobs.active = null;
            operation.hide();
            finishJob(current, quietSuccess);
            if (onDone && (current.outcome === 'done' || current.outcome === 'signals_sent')) {
              try { await onDone(current.result, current); } catch (error) { fail(error); }
            }
            resolve(current);
            return;
          }
          setTimeout(poll, current.state === 'confirm' ? 400 : 200);
        };
        poll();
      }).catch((error) => { fail(error); notify('Not started', error.message); resolve(null); });
    });
  }

  function finishJob(job, quietSuccess) {
    const title = job.title;
    switch (job.outcome) {
      case 'signals_sent':
        minute(`${title}: signals sent. ${AFTER[job.kind] || ''} The Volca does not confirm reception over audio.`, 'good');
        celebrate('sent');
        notify('Signals sent', `${AFTER[job.kind] || ''} The Browser App played every signal; only the Volca can show what it received.`);
        break;
      case 'cancelled_before_sending':
        minute(`${title}: cancelled before sending. Nothing reached the Volca.`);
        break;
      case 'interrupted':
        minute(`${title}: ${job.error}`, 'error');
        notify('Stopped while sending', job.error);
        break;
      case 'cancelled':
        minute(`${title}: cancelled. Nothing was changed.`);
        break;
      case 'failed':
        minute(`${title}: ${job.error}`, 'error');
        notify('Not completed', job.error);
        break;
      default:
        if (!quietSuccess) minute(`${title}: done.`, 'good');
    }
  }

  // ------------------------------------------------------------------ selectable lists
  class Picker {
    constructor(el, { render, onChange, onActivate, onKey, empty }) {
      this.el = el; this.items = []; this.selected = new Set(); this.anchor = null; this.focus = null;
      this.render = render; this.onChange = onChange || (() => {}); this.onActivate = onActivate; this.onKey = onKey; this.empty = empty;
      el.addEventListener('keydown', (event) => this.key(event));
      el.addEventListener('click', (event) => {
        const row = event.target.closest('.item');
        if (!row) return;
        const index = Number(row.dataset.index);
        if (event.shiftKey && this.anchor !== null) this.range(this.anchor, index, event.ctrlKey || event.metaKey);
        else if (event.ctrlKey || event.metaKey) { this.toggle(index); this.anchor = index; }
        else { this.only(index); }
        this.focus = index;
        this.paint();
      });
      el.addEventListener('dblclick', (event) => { if (event.target.closest('.item') && this.onActivate) this.onActivate(); });
    }
    setItems(items, keep = true) {
      const previous = keep ? new Set([...this.selected].map((i) => this.items[i] && this.items[i].key)) : new Set();
      this.items = items;
      this.selected = new Set(items.map((item, i) => (previous.has(item.key) ? i : -1)).filter((i) => i >= 0));
      if (this.focus !== null && this.focus >= items.length) this.focus = items.length ? items.length - 1 : null;
      this.draw();
    }
    select(indices) { this.selected = new Set(indices.filter((i) => i >= 0 && i < this.items.length)); this.focus = indices.length ? indices[indices.length - 1] : this.focus; this.anchor = indices[0] ?? null; this.paint(); }
    only(index) { this.selected = new Set([index]); this.anchor = index; }
    toggle(index) { if (this.selected.has(index)) this.selected.delete(index); else this.selected.add(index); }
    range(from, to, add) {
      if (!add) this.selected.clear();
      const [a, b] = from < to ? [from, to] : [to, from];
      for (let i = a; i <= b; i++) this.selected.add(i);
    }
    indices() { return [...this.selected].sort((a, b) => a - b); }
    chosen() { return this.indices().map((i) => this.items[i]); }
    draw() {
      const rows = this.items.map((item, index) => {
        const row = this.render(item, index);
        row.classList.add('item');
        row.dataset.index = index;
        row.id = `${this.el.id}-${index}`;
        row.setAttribute('role', 'option');
        return row;
      });
      this.el.replaceChildren(...(rows.length ? rows : [h('div', { class: 'empty' }, this.empty || 'Nothing here yet.')]));
      this.paint();
    }
    paint() {
      for (const row of this.el.children) {
        if (!row.dataset.index) continue;
        const index = Number(row.dataset.index);
        row.setAttribute('aria-selected', this.selected.has(index) ? 'true' : 'false');
        row.classList.toggle('focus', index === this.focus);
      }
      if (this.focus !== null) {
        const row = this.el.children[this.focus];
        if (row && row.dataset.index) { this.el.setAttribute('aria-activedescendant', row.id); row.scrollIntoView({ block: 'nearest' }); }
      }
      this.onChange(this);
    }
    key(event) {
      if (this.onKey && this.onKey(event) === true) { event.preventDefault(); return; }
      const count = this.items.length;
      if (!count) return;
      const current = this.focus ?? -1;
      let next = null;
      if (event.key === 'ArrowDown') next = Math.min(count - 1, current + 1);
      else if (event.key === 'ArrowUp') next = Math.max(0, current - 1);
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = count - 1;
      else if (event.key === 'PageDown') next = Math.min(count - 1, current + 10);
      else if (event.key === 'PageUp') next = Math.max(0, current - 10);
      else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault(); this.selected = new Set(this.items.map((_, i) => i)); this.paint(); return;
      } else if (event.key === 'Enter' && this.onActivate) { event.preventDefault(); this.onActivate(); return; }
      if (next === null || event.altKey) return;
      event.preventDefault();
      if (event.shiftKey) { if (this.anchor === null) this.anchor = Math.max(0, current); this.range(this.anchor, next, false); }
      else if (!(event.ctrlKey || event.metaKey)) this.only(next);
      this.focus = next;
      this.paint();
    }
  }

  // ------------------------------------------------------------------ state
  const S = { libraries: [], samples: [], draft: null, devices: null, bank: null, catalog: null, firmware: [], kits: [] };
  let activeSampleList = 'library';

  // ------------------------------------------------------------------ spaces
  function go(space) {
    $$('.spaces button').forEach((b) => (b.dataset.space === space ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current')));
    for (const section of $$('.space')) section.hidden = section.id !== `space-${space}`;
    document.title = `${$(`#space-${space}`).dataset.title} · VolcaStudio XL Browser App`;
    try { sessionStorage.setItem('wmc-space', space); } catch (e) { /* ignore */ }
    const loaders = { commons: loadKits, memory: loadBanks, movement: loadMovement, firmware: loadFirmware, connections: loadDevices };
    if (loaders[space]) attempt(loaders[space]);
  }
  $$('.spaces button').forEach((b) => b.addEventListener('click', () => go(b.dataset.space)));
  $$('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));

  // ------------------------------------------------------------------ libraries
  const library = new Picker($('#library-list'), {
    empty: 'No WAV files here. Use “Add samples…” or “Add a folder…”.',
    render: (item) => h('div', { draggable: 'false' },
      h('span', { class: 'slot' }, '◇'),
      h('span', { class: 'name', title: item.path }, item.name, item.group ? h('span', { class: 'group' }, item.group) : null),
      h('span', { class: 'meta' }, fmt.bytes(item.size))),
    onActivate: () => addSelectedToKit(),
    onKey: (event) => {
      if (event.key === ' ') { listen(library.chosen()[0]); return true; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') { makeVariants(library); return true; }
      if (!event.ctrlKey && !event.metaKey && !event.altKey && /^[jk]$/i.test(event.key)) { varispeed(event.key.toLowerCase() === 'j' ? -1 : 1, library); return true; }
      return false;
    },
    onChange: () => {
      const chosen = library.chosen();
      $('#add-to-kit').disabled = !chosen.length;
      $('#add-to-kit').textContent = chosen.length > 1 ? `Add ${chosen.length} to workbench` : 'Add to workbench';
      $('#add-to-kit').append(' ', h('kbd', {}, 'Enter'));
      if (chosen.length === 1) { showDetail(chosen[0].path); autoplaySelection(chosen[0]); }
    },
  });

  let libraryOffset = 0, librarySerial = 0, libraryTimer = null;
  async function loadLibraries(prefer) {
    const { libraries, registrations } = await get('/api/libraries');
    S.libraries = libraries;
    S.registrations = registrations;
    const select = $('#library-select');
    const previous = prefer || select.value || '*';
    select.replaceChildren(h('option', { value: '*' }, 'All samples'), ...libraries.map((l) => h('option', { value: l.id }, `${l.title} · ${{ wmc: 'Browser App copy', shared: 'registered folder', kits: 'saved kits', packs: 'existing packs', variants: 'generated' }[l.kind]}`)));
    select.value = previous === '*' || libraries.some((l) => l.id === previous) ? previous : '*';
    libraryOffset = 0;
    await loadSamples();
  }
  async function loadSamples() {
    const serial = ++librarySerial;
    const id = $('#library-select').value;
    const entry = S.libraries.find((l) => l.id === id);
    $('#library-remove').hidden = !entry || !entry.removable;
    const data = await get(`/api/library?id=${q(id)}&q=${q($('#library-search').value.trim())}&offset=${libraryOffset}&limit=250`);
    if (serial !== librarySerial) return;
    S.samples = data.samples.map((sample) => ({ ...sample, key: sample.path }));
    library.setItems(S.samples);
    $('#library-count').textContent = `${data.total} samples` + (data.total ? ` · ${data.offset + 1}–${data.offset + data.samples.length} shown` : '');
    $('#library-previous').disabled = data.offset === 0;
    $('#library-next').disabled = !data.has_more;
  }
  $('#library-select').addEventListener('change', () => { libraryOffset = 0; attempt(loadSamples); });
  $('#library-search').addEventListener('input', () => {
    clearTimeout(libraryTimer);
    ++librarySerial;
    libraryTimer = setTimeout(() => { libraryOffset = 0; attempt(loadSamples); }, 180);
  });
  $('#library-search').addEventListener('keydown', (event) => { if (event.key === 'ArrowDown') { event.preventDefault(); $('#library-list').focus(); library.key(event); } });
  $('#library-refresh').addEventListener('click', () => attempt(() => loadLibraries()));
  $('#library-previous').addEventListener('click', () => { libraryOffset = Math.max(0, libraryOffset - 250); attempt(loadSamples); });
  $('#library-next').addEventListener('click', () => { libraryOffset += 250; attempt(loadSamples); });
  $('#add-to-kit').addEventListener('click', () => addSelectedToKit());
  $('#library-lower').addEventListener('click', () => varispeed(-1, library));
  $('#library-raise').addEventListener('click', () => varispeed(1, library));
  $('#library-x2').addEventListener('click', () => makeVariants(library));
  $('#library-manage').addEventListener('click', () => attempt(async () => {
    const data = await get('/api/libraries');
    const path = h('input', { id: 'registration-path', type: 'text', 'aria-label': 'Folder path', placeholder: 'Full path of a folder on this computer', autocomplete: 'off', spellcheck: 'false' });
    const name = h('input', { id: 'registration-name', type: 'text', 'aria-label': 'Library name', placeholder: 'Optional name', autocomplete: 'off' });
    const entries = data.registrations.map((entry) => h('li', {},
      h('strong', {}, entry.name), ` · ${entry.directory}${entry.available ? '' : ' · unavailable'}`, ' ',
      h('button', { type: 'button', class: 'small', onclick: () => $('#dialog').close('remove:' + entry.name) }, 'Unregister')));
    const answer = await ask({ title: 'Library registrations', wide: true, body: [
      h('p', {}, 'Register a folder in place to use it in both editions. The Browser App reads its WAV files without copying the library.'),
      h('label', {}, 'Folder path', path), h('label', {}, 'Library name (optional)', name),
      h('ul', { class: 'plain' }, entries.length ? entries : h('li', {}, 'No registered folders.'))],
      actions: [{ label: 'Close', value: '', default: true }, { label: 'Register folder', value: 'register', kind: 'primary' }] });
    if (answer === 'register') {
      const added = await post('/api/library/register', { directory: path.value.trim(), name: name.value.trim() || null });
      await loadLibraries(added.id);
      minute(`Registered ${added.name}: ${added.directory}.`);
    } else if (answer.startsWith('remove:')) {
      const id = answer.slice(7);
      const confirmed = await ask({ title: `Unregister “${id}”?`, body: 'This removes the shared library reference. Files remain in their folder. Unsaved workbench entries from that folder may become unavailable until it is registered again.',
        actions: [{ label: 'Keep', value: '', default: true }, { label: 'Unregister', value: 'yes', kind: 'primary' }] });
      if (confirmed === 'yes') { await post('/api/library/unregister', { name: id }); await loadLibraries(); setDraft(await get('/api/draft')); }
    }
  }));
  $('#library-remove').addEventListener('click', () => attempt(async () => {
    const id = $('#library-select').value;
    const entry = S.libraries.find((l) => l.id === id);
    const answer = await ask({ title: `Remove the Browser App's copy of “${entry.title}”?`, body: [
      'This deletes the copies the Browser App made when you added this folder. Your original files elsewhere are not touched. Saved kits keep their own copies.'],
      actions: [{ label: 'Keep it', value: '', default: true }, { label: 'Remove copy', value: 'yes', kind: 'send' }] });
    if (answer !== 'yes') return;
    await post('/api/library/remove', { id });
    minute(`Removed the Browser App's copy of ${entry.title}.`);
    await loadLibraries();
  }));

  async function addSelectedToKit() {
    const chosen = library.chosen();
    if (!chosen.length) return;
    await attempt(async () => {
      const before = S.draft ? S.draft.count : 0;
      setDraft(await post('/api/draft/add', { paths: chosen.map((c) => c.path) }));
      workbench.select(chosen.map((_, i) => before + i));
      minute(`Added ${chosen.length} sample${chosen.length === 1 ? '' : 's'} to the workbench.`);
    });
  }

  // Uploads: the browser hands the Browser App a copy; nothing on disk is moved or changed.
  async function importFiles(files, libraryName, relative) {
    const accepted = files.filter((f) => /\.(wav|json)$/i.test(f.name) && !/(^|\/)\./.test(relative(f)));
    const skipped = files.length - accepted.length;
    if (!accepted.length) { notify('Nothing to add', 'Choose WAV files (or a folder containing them).'); return; }
    accepted.sort((a, b) => Number(/\.json$/i.test(a.name)) - Number(/\.json$/i.test(b.name)));
    let stop = false, done = 0, reused = 0;
    const failed = [];
    operation.show('Adding samples', `0 / ${accepted.length}`, () => { stop = true; });
    for (const file of accepted) {
      if (stop) break;
      try {
        const result = await api('PUT', '/api/import/sample', file, { headers: { 'X-WMC-Library': q(libraryName), 'X-WMC-Path': q(relative(file)) } });
        if (result.reused) reused += 1;
      } catch (error) {
        if (error.status === 401 || error.status === 0) { stop = true; break; }
        failed.push(`${file.name}: ${error.message}`);
      }
      done += 1;
      operation.message(`${done} / ${accepted.length} · ${file.name}`);
      operation.progress(done, accepted.length);
    }
    operation.hide();
    minute(`Library “${libraryName}”: ${done - failed.length} file${done - failed.length === 1 ? '' : 's'} copied${reused ? ` (${reused} already there)` : ''}${skipped ? `, ${skipped} non-WAV skipped` : ''}${stop ? ', stopped early' : ''}.`, failed.length ? 'error' : 'good');
    if (failed.length) notify('Some files were not added', failed.slice(0, 8).join('\n') + (failed.length > 8 ? `\n…and ${failed.length - 8} more.` : ''));
    await loadLibraries(`wmc:${libraryName}`);
  }
  const slug = (text) => text.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 40) || 'samples';
  $('#add-files').addEventListener('change', (event) => {
    const files = [...event.target.files];
    event.target.value = '';
    attempt(() => importFiles(files, 'added-samples', (f) => f.name));
  });
  $('#add-folder').addEventListener('change', (event) => {
    const files = [...event.target.files];
    event.target.value = '';
    if (!files.length) return;
    const top = (files[0].webkitRelativePath || files[0].name).split('/')[0];
    attempt(() => importFiles(files, slug(top), (f) => (f.webkitRelativePath || f.name).split('/').slice(1).join('/') || f.name));
  });

  // ------------------------------------------------------------------ workbench
  let dragFrom = null;
  const workbench = new Picker($('#workbench-list'), {
    empty: 'Your workbench is empty. Select library samples and press Enter.',
    render: (row, index) => {
      const el = h('div', { draggable: 'true', class: row.error ? 'error' : '' },
        h('span', { class: 'slot' }, fmt.slot(index)),
        h('span', { class: 'name', title: row.path }, row.name,
          row.error ? h('span', { class: 'group' }, row.error) : row.original && row.original !== row.name ? h('span', { class: 'group' }, `from ${row.original}`) : null),
        h('span', { class: 'meta' }, row.label ? h('span', { class: 'badge-shift', title: `${row.semitones} semitones in total · speed ×${row.factor.toFixed(4)}${row.uncertain ? ' · earlier history uncertain' : ''}` }, row.label) : '', ' ', `${fmt.s(row.seconds)} s`));
      el.addEventListener('dragstart', (event) => {
        dragFrom = workbench.selected.has(index) ? workbench.indices() : [index];
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', 'wmc-slots');
        el.classList.add('dragging');
      });
      el.addEventListener('dragend', () => el.classList.remove('dragging'));
      el.addEventListener('dragover', (event) => { if (dragFrom) { event.preventDefault(); el.classList.add('drop-before'); } });
      el.addEventListener('dragleave', () => el.classList.remove('drop-before'));
      el.addEventListener('drop', (event) => { event.preventDefault(); el.classList.remove('drop-before'); moveTo(dragFrom, index); dragFrom = null; });
      return el;
    },
    onKey: (event) => {
      if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) { move(event.key === 'ArrowUp' ? -1 : 1); return true; }
      if (event.key === ' ') { listen(workbench.chosen()[0]); return true; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') { makeVariants(workbench); return true; }
      if (event.key === 'Delete' || event.key === 'Backspace') { removeSelected(); return true; }
      if (!event.ctrlKey && !event.metaKey && !event.altKey && (event.key === 'j' || event.key === 'J')) { varispeed(-1); return true; }
      if (!event.ctrlKey && !event.metaKey && !event.altKey && (event.key === 'k' || event.key === 'K')) { varispeed(1); return true; }
      return false;
    },
    onChange: () => {
      const chosen = workbench.chosen();
      if (chosen.length === 1) { showDetail(chosen[0].path); autoplaySelection(chosen[0]); }
    },
  });

  function setDraft(draft) {
    S.draft = draft;
    workbench.setItems(draft.rows.map((r, i) => ({ ...r, key: `${i}:${r.path}` })), false);
    const meter = $('#budget');
    $('#budget-slots').textContent = `${fmt.slot(draft.count)} / 100 slots`;
    $('#budget-seconds').textContent = `${fmt.s(draft.seconds)} / 65.00 s`;
    $('#budget-bar').style.width = `${Math.min(100, (100 * draft.seconds) / draft.max_seconds)}%`;
    meter.classList.toggle('over', draft.over_budget);
    meter.setAttribute('aria-label', `Kit budget: ${draft.count} of 100 slots, ${fmt.s(draft.seconds)} of 65 seconds${draft.over_budget ? ', over budget' : ''}`);
    const badge = $('#edit-badge');
    badge.hidden = !draft.edit;
    if (draft.edit) badge.textContent = `editing ${draft.name}`;
    $('#replace-kit').hidden = !draft.edit;
    if (draft.edit) $('#replace-kit').textContent = `Replace “${draft.name}” (keeps the old version)`;
    if (draft.name && !$('#kit-name').value) $('#kit-name').value = draft.edit ? '' : draft.name;
    const saved = draft.saved_kit;
    $('#send-kit').disabled = !saved;
    $('#check-kit').disabled = !saved;
    $('#export-kit-signals').disabled = !saved;
    $('#kit-status').textContent = saved
      ? `Ready: “${saved.split(/[\\/]/).pop()}” is saved. Sending replaces all 100 sample slots and asks again first.`
      : draft.over_budget ? 'Over budget: a kit holds up to 100 samples and 65 seconds of final audio.'
        : draft.missing ? 'Some samples are missing; remove them before saving.'
          : 'Save first. Sending replaces all 100 sample slots and always asks again.';
  }
  async function putDraft(paths, select) {
    setDraft(await put('/api/draft', { paths, generation: S.draft.generation }));
    if (select) workbench.select(select);
  }
  const paths = () => S.draft.rows.map((r) => r.path);
  function move(offset) {
    const selected = workbench.indices();
    if (!selected.length) return;
    const list = paths();
    if (offset < 0 && selected[0] === 0) return;
    if (offset > 0 && selected[selected.length - 1] === list.length - 1) return;
    const order = list.map((_, i) => i);
    const moving = new Set(selected);
    if (offset < 0) { for (const i of selected) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; } }
    else { for (const i of [...selected].reverse()) { [order[i + 1], order[i]] = [order[i], order[i + 1]]; } }
    attempt(() => putDraft(order.map((i) => list[i]), order.map((i, pos) => (moving.has(i) ? pos : -1)).filter((p) => p >= 0)));
  }
  function moveTo(from, target) {
    if (!from || !from.length) return;
    const list = paths();
    const moving = new Set(from);
    const kept = list.map((p, i) => [p, i]).filter(([, i]) => !moving.has(i));
    const insertAt = kept.findIndex(([, i]) => i >= target);
    const block = from.map((i) => [list[i], i]);
    const result = insertAt < 0 ? [...kept, ...block] : [...kept.slice(0, insertAt), ...block, ...kept.slice(insertAt)];
    const start = insertAt < 0 ? kept.length : insertAt;
    attempt(() => putDraft(result.map(([p]) => p), block.map((_, n) => start + n)));
  }
  function removeSelected() {
    const selected = new Set(workbench.indices());
    if (!selected.size) return;
    const first = Math.min(...selected);
    attempt(() => putDraft(paths().filter((_, i) => !selected.has(i)), [Math.min(first, S.draft.count - selected.size - 1)]));
  }
  async function varispeed(direction, picker = workbench) {
    const indices = picker.indices();
    if (!indices.length) { notify('Select samples first', 'Select one or more samples in the library or workbench.'); return; }
    const semitones = await semitonePrompt(direction, indices.length);
    if (semitones === null) return;
    if (semitones === 0) { minute('Zero semitones: nothing to change.'); return; }
    const request = picker === library ? post('/api/samples/variants', { paths: picker.chosen().map((item) => item.path), semitones, replace_existing: true }) : post('/api/draft/varispeed', { indices, semitones });
    await runJob(request, { quietSuccess: true, onDone: (result) => {
      setDraft(result.draft);
      workbench.select(result.selected);
      minute(`Varispeed ${fmt.shift(semitones)} applied to ${indices.length} sample${indices.length === 1 ? '' : 's'}. Check the kit duration before saving.`, 'good');
      $('#workbench-list').focus();
    } });
  }
  async function makeVariants(picker = workbench) {
    const chosen = picker.chosen();
    if (!chosen.length) { notify('Select samples first', 'Choose the samples to make ×2 variants.'); return; }
    await runJob(post('/api/samples/variants', { paths: chosen.map((item) => item.path), semitones: 12 }), { quietSuccess: true, onDone: (result) => {
      setDraft(result.draft);
      workbench.select(result.selected);
      minute('Added ×2 variants: one octave higher and half the duration. Original workbench entries remain.');
    } });
  }
  $$('.toolbar button').forEach((button) => button.addEventListener('click', () => {
    const act = button.dataset.act;
    if (act === 'up') move(-1);
    else if (act === 'down') move(1);
    else if (act === 'remove') removeSelected();
    else if (act === 'lower') varispeed(-1);
    else if (act === 'raise') varispeed(1);
    else if (act === 'x2') makeVariants();
    else if (act === 'align') openAlignment();
    else if (act === 'clear') attempt(async () => {
      const answer = await ask({ title: 'Clear the workbench?', body: 'Saved kits and library files are not affected.', actions: [{ label: 'Keep', value: '', default: true }, { label: 'Clear', value: 'yes', kind: 'primary' }] });
      if (answer === 'yes') { setDraft(await post('/api/draft/clear')); $('#kit-name').value = ''; }
    });
  }));

  $('#save-kit').addEventListener('click', () => saveKit());
  async function saveKit() {
    const name = $('#kit-name').value.trim();
    if (!name) { $('#kit-name').focus(); notify('Name the kit', 'Use lowercase letters, digits, dots, dashes or underscores, for example dusty-breaks.'); return; }
    await attempt(async () => {
      const result = await post('/api/kit/save', { name });
      setDraft(result.draft);
      minute(`Saved kit “${result.name}” as independent copies. Nothing was sent.`, 'good');
      const awards = result.draft.awards || [];
      celebrate(awards.length ? awards[awards.length - 1] : 'saved');
    });
  }
  $('#replace-kit').addEventListener('click', () => attempt(async () => {
    const answer = await ask({ title: `Replace “${S.draft.name}”?`, body: ['The saved kit is replaced by this workbench. Its previous version goes to the archive in Commons and can be restored.'],
      actions: [{ label: 'Cancel', value: '', default: true }, { label: 'Replace & archive previous', value: 'yes', kind: 'primary' }] });
    if (answer !== 'yes') return;
    const result = await post('/api/kit/replace');
    setDraft(result.draft);
    minute(`Replaced kit “${result.name}”; the previous version is archived.`, 'good');
    celebrate('saved');
  }));
  $('#send-kit').addEventListener('click', () => sendKit(S.draft && S.draft.saved_kit));
  $('#check-kit').addEventListener('click', () => checkKit(S.draft && S.draft.saved_kit));
  $('#export-kit-signals').addEventListener('click', () => exportSignals('/api/kit/export-signals', { path: S.draft && S.draft.saved_kit }));
  async function exportSignals(endpoint, body) {
    const consequence = endpoint.includes('/kit/')
      ? 'Kit clear signals erase all 100 sample slots when played to SYNC IN.'
      : 'Playing these signals to SYNC IN replaces the chosen pattern memories; sample audio is not included.';
    const answer = await ask({ title: 'Prepare SYRO files for download?', body: 'The ZIP contains data-audio WAVs and a manifest. Do not audition these WAVs through speakers or headphones. Preparation sends nothing to the Volca. ' + consequence,
      actions: [{ label: 'Cancel', value: '', default: true }, { label: 'Prepare download', value: 'yes', kind: 'primary' }] });
    if (answer !== 'yes') return;
    await runJob(post(endpoint, body), { quietSuccess: true, onDone: async (result) => {
      await download(result.download, result.name);
      minute(`Downloaded ${result.name}. Nothing was sent to the Volca.`, 'good');
    } });
  }
  async function sendKit(path) {
    if (!path) return;
    await runJob(afterDevices(() => post('/api/kit/send', { path })));
  }
  async function checkKit(path) {
    if (!path) return;
    await runJob(post('/api/kit/prepare', { path }), { quietSuccess: true, onDone: (r) => {
      minute(`Checked offline: ${r.signals} signals for “${r.kit}” encoded and verified (${r.count} samples, ${fmt.s(r.seconds)} s). Nothing was sent.`, 'good');
    } });
  }

  // ------------------------------------------------------------------ listening & detail
  let player = null, detailTimer = null, detailFor = null, listenGeneration = 0, waveformGeneration = 0;
  let autoplayTimer = null, autoplayPath = null, listeningItem = null;
  function stopListening() {
    ++listenGeneration;
    clearTimeout(autoplayTimer);
    if (player) { player.pause(); URL.revokeObjectURL(player.src); player = null; }
  }
  async function previewBlob(path, pitch, mode = $('#preview-mode').value) {
    const response = await api('GET', `/api/sample/preview?pitch=${pitch}&mode=${mode}&path=${q(path)}`, undefined, { raw: true });
    return response.blob();
  }
  async function listen(item, automatic = false) {
    if (!item || jobs.active) return;
    if (!automatic && player && listeningItem === item.path) { stopListening(); return; }
    stopListening();
    const generation = listenGeneration;
    const waveGeneration = ++waveformGeneration;
    listeningItem = item.path;
    await attempt(async () => {
      const blob = await previewBlob(item.path, $('#preview-pitch').value);
      if (generation !== listenGeneration || jobs.active) return;
      const audio = new Audio(URL.createObjectURL(blob));
      player = audio;
      audio.addEventListener('ended', () => { if (player === audio) stopListening(); });
      try { await audio.play(); } catch (error) { if (player === audio) stopListening(); throw error; }
      if (generation !== listenGeneration) { audio.pause(); return; }
      drawWave(blob, waveGeneration);
    });
  }
  function autoplaySelection(item) {
    if (!$('#autoplay').checked || jobs.active || autoplayPath === item.path) return;
    autoplayPath = item.path;
    stopListening();
    autoplayTimer = setTimeout(() => listen(item, true), 160);
  }
  for (const name of ['library', 'workbench']) {
    for (const event of ['focusin', 'pointerdown']) $(`#${name}-list`).addEventListener(event, () => { activeSampleList = name; });
  }
  const activeSample = () => activeSampleList === 'library'
    ? library.chosen()[0] || workbench.chosen()[0] : workbench.chosen()[0] || library.chosen()[0];
  $('#listen').addEventListener('click', () => listen(activeSample()));
  $('#stop-listen').addEventListener('click', stopListening);
  $('#autoplay').addEventListener('change', (event) => attempt(async () => {
    await post('/api/preferences', { autoplay: event.target.checked });
    autoplayPath = null;
    if (event.target.checked) { const item = activeSample(); if (item) autoplaySelection(item); }
    else stopListening();
  }));
  $('#preview-mode').addEventListener('change', () => attempt(async () => {
    stopListening();
    await post('/api/preferences', { preview_mode: $('#preview-mode').value });
    detailFor = null;
    const item = activeSample();
    if (item) showDetail(item.path);
  }));
  $('#preview-pitch').addEventListener('change', stopListening);

  async function drawWave(blob, generation = ++waveformGeneration) {
    const canvas = $('#waveform');
    const context = canvas.getContext('2d');
    const style = getComputedStyle(document.documentElement);
    try {
      // Waveform inspection only decodes data. It needs no live audio output.
      const audio = new OfflineAudioContext(1, 1, 44100);
      const buffer = await audio.decodeAudioData(await blob.arrayBuffer());
      if (generation !== waveformGeneration) return;
      context.clearRect(0, 0, canvas.width, canvas.height);
      const data = buffer.getChannelData(0);
      const step = Math.max(1, Math.floor(data.length / canvas.width));
      context.fillStyle = style.getPropertyValue('--ink').trim() || '#1c2231';
      for (let x = 0; x < canvas.width; x++) {
        let min = 1, max = -1;
        for (let i = x * step; i < Math.min(data.length, (x + 1) * step); i++) { min = Math.min(min, data[i]); max = Math.max(max, data[i]); }
        if (max < min) break;
        const top = ((1 - max) / 2) * canvas.height, bottom = ((1 - min) / 2) * canvas.height;
        context.fillRect(x, top, 1, Math.max(1, bottom - top));
      }
    } catch (error) { /* decoding is cosmetic */ }
  }
  function showDetail(path) {
    const generation = ++waveformGeneration;
    clearTimeout(detailTimer);
    detailTimer = setTimeout(async () => {
      if (detailFor === path) return;
      detailFor = path;
      const dl = $('#sample-detail');
      dl.replaceChildren(h('dt', {}, 'Sample'), h('dd', {}, path.split(/[\\/]/).pop()), h('dt', {}, 'Pitch'), h('dd', {}, 'listening…'));
      try {
        const info = await get(`/api/sample/info?path=${q(path)}`);
        if (detailFor !== path) return;
        const p = info.pitch;
        const pitch = p.note ? `${p.note} · ${p.hz} Hz · ${p.cents > 0 ? '+' : ''}${p.cents} cents · confidence ${Math.round(p.confidence * 100)}%` : `unclear (${p.status})`;
        dl.replaceChildren(
          h('dt', {}, 'Sample'), h('dd', {}, info.name),
          h('dt', {}, 'Source format'), h('dd', {}, `${info.format.sample_rate} Hz · ${info.format.bits}-bit · ${info.format.channels === 1 ? 'mono' : 'stereo'}`),
          h('dt', {}, 'Duration'), h('dd', {}, `${info.seconds.toFixed(3)} s · ${info.memory_percent.toFixed(1)}% of the Volca's memory`),
          h('dt', {}, 'Varispeed'), h('dd', {}, info.semitones ? `${fmt.shift(info.semitones)} semitones in total (speed ×${info.factor.toFixed(4)})${info.uncertain ? ' · earlier history uncertain' : ''}` : 'none'),
          h('dt', {}, 'Original'), h('dd', {}, info.original),
          h('dt', {}, 'Filename note'), h('dd', {}, info.filename_note || '—'),
          h('dt', {}, 'Measured'), h('dd', {}, pitch),
          h('dt', {}, 'At SPEED −12/−24'), h('dd', {}, info.at_speed.minus12 ? `${info.at_speed.minus12} / ${info.at_speed.minus24}` : '—'));
        const blob = await previewBlob(path, 0);
        if (generation === waveformGeneration) drawWave(blob, generation);
      } catch (error) {
        if (detailFor === path) dl.replaceChildren(h('dt', {}, 'Sample'), h('dd', {}, error.message));
      }
    }, 300);
  }

  // ------------------------------------------------------------------ alignment
  const A = { open: false };
  async function openAlignment() {
    if (!S.draft || !S.draft.count) { notify('Nothing to align', 'Add samples to the workbench first, then choose a master and slaves.'); return; }
    const dialog = $('#align-dialog');
    Object.assign(A, { open: true, rows: S.draft.rows, analysis: null, plan: null, master: 0, slaves: new Set(S.draft.rows.map((_, i) => i).filter((i) => i > 0)),
      choices: {}, overrides: {}, picked: new Set(), generation: S.draft.generation, timer: null, requested: 0 });
    $('#align-master').replaceChildren(...A.rows.map((r, i) => h('option', { value: i }, `${fmt.slot(i)}  ${r.name}`)));
    $('#align-master').value = '0';
    $('#align-summary').textContent = 'Listening to every sample for pitch… Nothing changes until you accept.';
    $('#align-accept').disabled = true;
    drawAlignTable();
    dialog.showModal();
    const job = await runJob(post('/api/align/analyze'), { quietSuccess: true });
    if (!A.open) return;
    if (!job || job.outcome !== 'done') { $('#align-summary').textContent = 'Analysis did not complete. Close and try again.'; return; }
    if (job.result.generation !== A.generation) { $('#align-summary').textContent = 'The workbench changed during analysis. Close and open again.'; return; }
    A.analysis = job.result.rows;
    drawAlignTable();
    schedulePlan();
  }
  function drawAlignTable() {
    const body = $('#align-table tbody');
    body.replaceChildren(...A.rows.map((row, i) => {
      const info = A.analysis ? A.analysis[i] : null;
      const plan = A.plan ? A.plan.rows[i] : null;
      const isMaster = i === A.master;
      const slave = h('input', { type: 'checkbox', 'aria-label': `Slave ${fmt.slot(i)}`, checked: A.slaves.has(i), disabled: isMaster });
      slave.addEventListener('change', () => { if (slave.checked) A.slaves.add(i); else { A.slaves.delete(i); delete A.overrides[i]; } schedulePlan(); });
      const source = h('select', { 'aria-label': `Pitch source for ${fmt.slot(i)}` });
      if (!info) source.append(h('option', {}, '…'));
      else {
        if (info.conflict) source.append(h('option', { value: '' }, 'Choose…'));
        if (info.filename_pc !== null) source.append(h('option', { value: 'filename' }, `Filename (${info.filename_note})`));
        if (info.detected_pc !== null && !info.uncertain) source.append(h('option', { value: 'detected' }, `Measured (${info.detected_note})`));
        if (!source.children.length) source.append(h('option', { value: '' }, 'No clear pitch'));
        source.value = A.choices[i] || (info.conflict ? '' : source.firstChild.value);
        source.disabled = !info.conflict && source.children.length < 2;
      }
      source.addEventListener('change', () => { if (source.value) A.choices[i] = source.value; else delete A.choices[i]; schedulePlan(); });
      const manual = Object.prototype.hasOwnProperty.call(A.overrides, i);
      const shift = h('input', { type: 'number', min: '-99', max: '99', step: '1', value: manual ? A.overrides[i] : plan ? plan.shift : 0,
        'aria-label': `Additional semitones for ${fmt.slot(i)}`, disabled: isMaster || !A.slaves.has(i), title: manual ? 'Manual amount' : 'Automatic proposal; type to override' });
      shift.addEventListener('change', () => { const v = parseInt(shift.value, 10); if (Number.isInteger(v) && v >= -99 && v <= 99) { A.overrides[i] = v; schedulePlan(); } });
      const tr = h('tr', { class: [isMaster ? 'master' : '', plan && A.plan.conflicts.includes(i) ? 'conflict' : '', A.picked.has(i) ? 'selected' : ''].join(' ') },
        h('td', {}, slave),
        h('td', {}, `${fmt.slot(i)}  ${row.name}`, isMaster ? h('strong', {}, '  · master') : null),
        h('td', {}, plan ? `${plan.note || plan.detected_note || plan.filename_note || 'unclear'} [${fmt.shift(plan.semitones)}]` : row.label || '—'),
        h('td', {}, info ? info.filename_note || '—' : '…'),
        h('td', {}, info ? (info.detected_note ? `${info.detected_note} (${Math.round(info.confidence * 100)}%)` : 'unclear') : '…'),
        h('td', {}, source),
        h('td', {}, shift, manual ? ' manual' : ''),
        h('td', {}, plan ? `${plan.final_note || '—'} [${fmt.shift(plan.final_semitones)}]` : '…', plan && plan.excluded ? h('div', { class: 'hint' }, plan.reason) : null),
        h('td', { class: 'num' }, plan ? fmt.s(plan.final_seconds) : fmt.s(row.seconds)));
      tr.addEventListener('click', (event) => {
        if (event.target.closest('input, select')) return;
        if (event.ctrlKey || event.metaKey) { if (A.picked.has(i)) A.picked.delete(i); else A.picked.add(i); }
        else if (event.shiftKey && A.lastPick !== undefined) { const [a, b] = [Math.min(A.lastPick, i), Math.max(A.lastPick, i)]; for (let n = a; n <= b; n++) A.picked.add(n); }
        else A.picked = new Set([i]);
        A.lastPick = i;
        drawAlignTable();
      });
      return tr;
    }));
  }
  function schedulePlan() {
    A.plan = null;
    $('#align-accept').disabled = true;
    clearTimeout(A.timer);
    A.timer = setTimeout(requestPlan, 150);
  }
  async function requestPlan() {
    if (!A.open || !A.analysis) return;
    const ticket = ++A.requested;
    try {
      const plan = await post('/api/align/plan', { master: A.master, slaves: [...A.slaves], choices: A.choices, overrides: A.overrides, generation: A.generation });
      if (ticket !== A.requested || !A.open) return;
      A.plan = plan;
      drawAlignTable();
      const conflicts = plan.conflicts.map(fmt.slot).join(', ');
      const excluded = plan.excluded.map(fmt.slot).join(', ');
      let text = `Kit: ${fmt.s(plan.before_seconds)} → ${fmt.s(plan.seconds)} / 65.00 s.`;
      if (conflicts) text += ` Choose Filename or Measured for: ${conflicts}.`;
      if (excluded) text += ` Excluded (unchanged unless shifted manually): ${excluded}.`;
      if (plan.over_budget) text += ' OVER BUDGET — adjust shifts before accepting.';
      if (!plan.ready && !conflicts) text += ' Choose a master with a clear pitch.';
      $('#align-summary').textContent = text;
      $('#align-summary').classList.toggle('bad', !plan.ready || plan.over_budget);
      $('#align-accept').disabled = !plan.ready || plan.over_budget;
    } catch (error) {
      if (ticket === A.requested) $('#align-summary').textContent = `Cannot prepare this proposal: ${error.message}`;
    }
  }
  $('#align-master').addEventListener('change', () => { A.master = Number($('#align-master').value); A.slaves.delete(A.master); delete A.overrides[A.master]; drawAlignTable(); schedulePlan(); });
  $('#align-all').addEventListener('click', () => { A.slaves = new Set(A.rows.map((_, i) => i).filter((i) => i !== A.master)); drawAlignTable(); schedulePlan(); });
  $('#align-none').addEventListener('click', () => { A.slaves = new Set(); A.overrides = {}; drawAlignTable(); schedulePlan(); });
  $('#align-batch-set').addEventListener('click', () => {
    const value = parseInt($('#align-batch').value, 10);
    if (!Number.isInteger(value) || value < -99 || value > 99) return;
    for (const i of A.picked) if (A.slaves.has(i)) A.overrides[i] = value;
    schedulePlan();
  });
  $('#align-batch-auto').addEventListener('click', () => { for (const i of A.picked) delete A.overrides[i]; schedulePlan(); });
  function closeAlignment() {
    A.open = false;
    clearTimeout(A.timer);
    if (jobs.active) post('/api/job/cancel', { id: jobs.active }).catch(() => {});
    $('#align-dialog').close();
  }
  $('#align-cancel').addEventListener('click', closeAlignment);
  $('#align-dialog').addEventListener('cancel', (event) => { event.preventDefault(); closeAlignment(); });
  $('#align-accept').addEventListener('click', async () => {
    if (!A.plan || !A.plan.ready || A.plan.over_budget) return;
    $('#align-accept').disabled = true;
    const job = await runJob(post('/api/align/apply', { master: A.master, slaves: [...A.slaves], choices: A.choices, overrides: A.overrides, generation: A.generation }), {
      quietSuccess: true,
      onDone: (result) => {
        setDraft(result.draft);
        minute('Accepted the key alignment. The workbench now uses the aligned copies; save when ready.', 'good');
        celebrate('aligned');
      } });
    if (job && job.outcome === 'done') { A.open = false; $('#align-dialog').close(); }
    else $('#align-accept').disabled = false;
  });

  // ------------------------------------------------------------------ commons (kits)
  async function loadKits() {
    const { kits, trash } = await get('/api/kits');
    S.kits = kits;
    const body = $('#kits-table tbody');
    body.replaceChildren(...(kits.length ? kits.map((kit) => {
      const actions = h('div', { class: 'row' },
        h('button', { type: 'button', class: 'small', onclick: () => openKit(kit, false) }, 'Open to edit'),
        h('button', { type: 'button', class: 'small', onclick: () => openKit(kit, true) }, 'Open a copy'),
        h('button', { type: 'button', class: 'small', onclick: () => checkKit(kit.path), disabled: !!kit.error }, 'Check offline'),
        h('button', { type: 'button', class: 'small send', onclick: () => sendKit(kit.path), disabled: !!kit.error }, 'Send…'),
        h('button', { type: 'button', class: 'small', onclick: () => exportKit(kit) }, 'Export ZIP'),
        kit.kind === 'studio' ? h('button', { type: 'button', class: 'small quiet', onclick: () => deleteKit(kit) }, 'Move to archive') : null);
      const memory = kit.error ? kit.error : `${((100 * kit.seconds) / 65).toFixed(1)}%`;
      return h('tr', {}, h('td', {}, h('strong', {}, kit.name), kit.kind === 'pack' ? h('div', { class: 'hint' }, 'existing pack') : null),
        h('td', { class: 'num' }, kit.count ?? '—'), h('td', { class: 'num' }, kit.seconds !== undefined ? fmt.s(kit.seconds) : '—'),
        h('td', {}, memory), h('td', {}, actions));
    }) : [h('tr', {}, h('td', { colspan: 5, class: 'hint' }, 'No saved kits yet. Make one in Gathering.'))]));
    $('#trash-list').replaceChildren(...(trash.length ? trash.map((entry) => h('li', {},
      h('span', {}, h('strong', {}, entry.name), ` · ${entry.reason} · ${entry.id}`),
      h('button', { type: 'button', class: 'small', onclick: () => restoreKit(entry) }, 'Restore'))) : [h('li', { class: 'hint' }, 'The archive is empty.')]));
  }
  $('#kits-refresh').addEventListener('click', () => attempt(loadKits));
  async function openKit(kit, copy) {
    await attempt(async () => {
      setDraft(await post('/api/kit/open', { path: kit.path, copy }));
      $('#kit-name').value = copy ? '' : '';
      minute(copy ? `Opened a copy of “${kit.name}”. Save it under a new name.` : `Opened “${kit.name}” for editing. “Replace” keeps the previous version in the archive.`);
      go('gathering');
    });
  }
  async function deleteKit(kit) {
    await attempt(async () => {
      const answer = await ask({ title: `Move “${kit.name}” to the archive?`, body: 'It leaves your kits but stays recoverable from the archive below.', actions: [
        { label: 'Keep', value: '', default: true }, { label: 'Move to archive', value: 'yes', kind: 'primary' }] });
      if (answer !== 'yes') return;
      await post('/api/kit/delete', { path: kit.path });
      minute(`Moved “${kit.name}” to the archive.`);
      await loadKits();
    });
  }
  async function restoreKit(entry) {
    await attempt(async () => {
      const result = await post('/api/kit/restore', { id: entry.id });
      minute(`Restored ${result.path}.`, 'good');
      celebrate('restored');
      await loadKits();
    });
  }
  async function download(url, fallbackName) {
    const response = await api('GET', url, undefined, { raw: true });
    const blob = await response.blob();
    const match = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '');
    const link = h('a', { href: URL.createObjectURL(blob), download: match ? match[1] : fallbackName });
    document.body.append(link);
    link.click();
    setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    return match ? match[1] : fallbackName;
  }
  async function exportKit(kit) {
    await attempt(async () => {
      const name = await download(`/api/kit/export?path=${q(kit.path)}`, `${kit.name}.volcakit.zip`);
      minute(`Exported “${kit.name}” as ${name}: every file byte for byte, including varispeed metadata.`, 'good');
    });
  }
  $('#kit-import').addEventListener('change', (event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    attempt(async () => {
      const suggested = slug(file.name.replace(/\.volcakit\.zip$|\.zip$/i, ''));
      const name = await promptText({ title: 'Import kit ZIP', text: 'The kit is copied unchanged into your saved kits under a new name.', label: 'Kit name', value: suggested, pattern: /^[a-z0-9][a-z0-9._-]{0,63}$/ });
      if (!name) return;
      const result = await api('PUT', '/api/kit/import', file, { headers: { 'X-WMC-Name': q(name) } });
      minute(`Imported kit “${result.name}”.`, 'good');
      await loadKits();
    });
  });

  // ------------------------------------------------------------------ memory (patterns)
  const patternFirmware = () => $('#pattern-firmware').value;
  let bankViewRevision = 0;
  let bankListingRequest = 0;
  function memoryBoxes(container, onChange, isAbsent) {
    container.replaceChildren(...Array.from({ length: 10 }, (_, i) => {
      const box = h('input', { type: 'checkbox', value: i + 1, 'aria-label': `Memory ${i + 1}` });
      const label = h('label', { class: isAbsent && isAbsent(i + 1) ? 'absent' : '' }, String(i + 1), box);
      box.addEventListener('change', () => { label.classList.toggle('on', box.checked); onChange(); });
      return label;
    }));
  }
  const memoryValues = (container) => $$('input', container).filter((b) => b.checked).map((b) => Number(b.value));
  function setMemories(container, values) { $$('input', container).forEach((b) => { b.checked = values.includes(Number(b.value)); b.parentElement.classList.toggle('on', b.checked); }); }
  const slotsText = (values) => (values.length === 10 ? 'all' : values.join(','));

  async function loadBanks() {
    const revision = bankViewRevision;
    const request = ++bankListingRequest;
    const { banks, bank } = await get('/api/patterns');
    // A navigation listing may finish after an upload/open/reset. Never
    // replace that newer bank with the listing's earlier snapshot.
    if (revision !== bankViewRevision || request !== bankListingRequest) return;
    const select = $('#bank-select');
    select.replaceChildren(...(banks.length ? banks.map((b) => h('option', { value: b.path }, `${b.name}${b.format ? ' · ' + b.format : ''}`)) : [h('option', { value: '' }, 'No saved banks yet')]));
    showBank(bank);
  }
  function showBank(bank) {
    bankViewRevision += 1;
    S.bank = bank;
    if (groove.saved) grooveChanged();
    $('#bank-label').textContent = bank.loaded ? `· ${bank.label}` : '';
    const view = $('#bank-view');
    if (!bank.loaded) { view.replaceChildren(h('p', { class: 'hint' }, 'No bank loaded. Reset + groove does not need one.')); refreshMemoryHints(); return; }
    view.replaceChildren(...bank.patterns.map((p) => {
      const parts = p.parts.length ? h('details', {}, h('summary', {}, 'Parts: Predictability, microtiming, motion'),
        ...p.parts.map((part) => h('div', {},
          h('div', { class: 'hint' }, `Part ${part.part} · ${part.motion_cells} recorded motion cell${part.motion_cells === 1 ? '' : 's'} (kept byte-exact)`),
          h('div', { class: 'steps16', 'aria-label': `Part ${part.part} Predictability per step` }, h('span', { class: 'lbl' }, 'Pred.'),
            ...part.predictability.map((v, s) => h('span', { class: v === 'ALL' ? '' : 'p', title: `Step ${s + 1}: ${v} ${part.predictability_masks[s]}` }, v === 'ALL' ? '·' : v.slice(2)))),
          h('div', { class: 'steps16', 'aria-label': `Part ${part.part} microtiming per step` }, h('span', { class: 'lbl' }, 'Micro'),
            ...part.microtiming.map((v, s) => h('span', { class: v ? 't' : '', title: `Step ${s + 1}: ${v} microsteps` }, v ? String(v) : '·')))))) : null;
      return h('article', { class: 'memory-card' },
        h('h4', {}, h('span', {}, p.display === 'current' ? 'Current snapshot' : `Memory ${p.display}`), h('code', {}, p.format)),
        h('code', {}, `sha256 ${p.sha256.slice(0, 16)}…`),
        h('p', { class: 'hint' }, p.summary), p.error ? h('p', { class: 'hint' }, p.error) : null, parts);
    }));
    refreshMemoryHints();
  }
  function refreshMemoryHints() {
    const stored = compatibleMemories();
    memoryBoxes($('#restore-memories'), () => {}, (n) => !stored.includes(n));
    $$('#restore-memories input').forEach((box) => { box.disabled = !stored.includes(Number(box.value)); });
    setMemories($('#restore-memories'), stored);
    const snapshot = S.bank && S.bank.patterns.find((p) => p.slot === null && compatiblePattern(p));
    $('#current-send').disabled = !snapshot;
    $('#export-current-signals').disabled = !snapshot;
    updateGrooveScope();
  }
  function compatibleMemories() {
    return S.bank ? S.bank.patterns.filter((p) => p.slot !== null && compatiblePattern(p)).map((p) => p.slot + 1) : [];
  }
  const compatiblePattern = (pattern) => (pattern.compatible_profiles || [pattern.firmware]).includes(patternFirmware());
  $('#pattern-firmware').addEventListener('change', refreshMemoryHints);
  $('#bank-open').addEventListener('click', () => attempt(async () => {
    const path = $('#bank-select').value;
    if (!path) return;
    showBank(await post('/api/patterns/open', { path }));
    minute(`Opened bank ${path.split(/[\\/]/).pop()}.`);
  }));
  $('#bank-upload').addEventListener('change', (event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    attempt(async () => {
      showBank(await api('PUT', '/api/patterns/upload', file, { headers: { 'X-WMC-Name': q(file.name) } }));
      minute(`Opened ${file.name}. Save a copy to keep it in the Studio pattern library.`);
    });
  });
  $('#bank-download').addEventListener('click', () => attempt(async () => {
    if (!S.bank || !S.bank.path) { notify('Save first', 'Save the loaded bank under a name, then download it.'); return; }
    const name = await download(`/api/patterns/download?path=${q(S.bank.path)}`, 'bank.vspatterns');
    minute(`Downloaded ${name} (unchanged bytes).`);
  }));
  $('#bank-reset').addEventListener('click', () => attempt(async () => {
    showBank(await post('/api/patterns/reset', { slots: $('#reset-slots').value, firmware: patternFirmware() }));
    minute('Neutral patterns in the DataBeat OS 1.0 pattern format created offline. Nothing was saved or sent yet.');
  }));
  $('#bank-save').addEventListener('click', () => attempt(async () => {
    const result = await post('/api/patterns/save', { name: $('#bank-name').value });
    minute(`Saved bank ${result.name}. The Volca was not changed.`, 'good');
    await loadBanks();
  }));
  $('#restore-all').addEventListener('click', () => setMemories($('#restore-memories'), compatibleMemories()));
  $('#restore-none').addEventListener('click', () => setMemories($('#restore-memories'), []));
  $('#export-pattern-signals').addEventListener('click', () => exportSignals('/api/patterns/export-signals', { slots: slotsText(memoryValues($('#restore-memories'))), firmware: patternFirmware() }));
  $('#export-current-signals').addEventListener('click', () => {
    const destination = Number($('#current-destination').value);
    if (!destination) { notify('Choose a destination', 'Choose a memory from 1 to 10 for the current snapshot.'); return; }
    exportSignals('/api/patterns/export-signals', { current_destination: destination, firmware: patternFirmware() });
  });
  $('#patterns-send').addEventListener('click', () => {
    const values = memoryValues($('#restore-memories'));
    if (!values.length) { notify('Choose memories', 'Tick at least one memory present in the loaded bank.'); return; }
    runJob(afterDevices(() => post('/api/patterns/send', { slots: slotsText(values), firmware: patternFirmware(), reset_current_via_midi: $('#reset-current').checked })));
  });
  $('#current-send').addEventListener('click', () => {
    const value = Number($('#current-destination').value);
    if (!value) { notify('Choose a destination', 'Pick the memory (1–10) that should receive the current snapshot.'); return; }
    runJob(afterDevices(() => post('/api/patterns/send', { current_destination: value, firmware: patternFirmware() })));
  });
  $('#backup-start').addEventListener('click', () => attempt(async () => {
    const name = $('#backup-name').value.trim();
    if (!name) { $('#backup-name').focus(); notify('Name the backup', 'Use lowercase letters, digits, dots, dashes or underscores.'); return; }
    const answer = await ask({ title: 'Capture a pattern backup?', body: [
      h('p', {}, 'The Browser App sends MIDI Stop and the backup request to the Volca, then records its headphone output.'),
      h('ul', {}, h('li', {}, 'Computer MIDI OUT → Volca MIDI IN'), h('li', {}, 'Volca headphone output → the chosen computer input (no effects, no automatic gain)')),
      h('p', { class: 'hint' }, 'Playback stops. Keep the controls untouched for about two minutes. Only a complete bank with 11 CRC-valid frames is saved.')],
      actions: [{ label: 'Cancel', value: '', default: true }, { label: 'Start capture', value: 'yes', kind: 'primary' }] });
    if (answer !== 'yes') return;
    await runJob(afterDevices(() => post('/api/patterns/backup', { name })), { quietSuccess: true, onDone: (result) => {
      showBank(result.bank);
      minute(`Backup saved as ${result.name}: 10 memories and the current snapshot, CRC-checked.`, 'good');
      celebrate('backup');
      loadBanks();
    } });
  }));
  $('#decode-upload').addEventListener('change', (event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    attempt(async () => {
      const name = await promptText({ title: 'Decode a recorded backup', text: 'Only a complete recording with all 11 CRC-valid frames becomes a bank.', label: 'New bank name', value: slug(file.name.replace(/\.wav$/i, '')), pattern: /^[a-z0-9][a-z0-9._-]{0,63}$/ });
      if (!name) return;
      const result = await api('PUT', '/api/patterns/decode', file, { headers: { 'X-WMC-Name': q(name) } });
      minute(`Decoded ${file.name} into ${result.name}.`, 'good');
      await loadBanks();
    });
  });

  // ------------------------------------------------------------------ movement (grooves)
  const groove = { dirty: true, saved: null };
  function grooveChanged() {
    groove.dirty = true;
    $('#groove-send').disabled = true;
    $('#groove-status').textContent = groove.saved ? 'Changed since saving — apply & save again before sending.' : 'Save first. Nothing has been sent to the Volca.';
    updateGrooveScope();
  }
  function updateGrooveScope() {
    const values = memoryValues($('#groove-memories'));
    const reset = $('input[name="groove-mode"]:checked').value === 'reset';
    const stored = (S.bank && S.bank.stored) || [];
    const current = $('#groove-source').value === 'current';
    if (current) {
      const destination = Number($('#groove-destination').value);
      $('#groove-scope').textContent = !S.bank || !S.bank.has_current
        ? 'Open a bank containing a separate current snapshot in Memory.'
        : !destination ? 'Choose the destination memory for the current snapshot.'
          : `Use the bank’s current snapshot for memory ${destination}. ` + (reset ? 'Reset + groove clears its notes and motion before applying timing.' : 'Preserve keeps its notes, motion and other settings.') + (stored.includes(destination) ? ' The source bank contains a copy of the destination memory.' : ' The source bank has no backup of the destination memory.');
      return;
    }
    const missing = values.filter((n) => !stored.includes(n));
    let text = values.length ? `${values.length} memor${values.length === 1 ? 'y' : 'ies'} selected: ${values.join(', ')}. ` : 'Select at least one memory. ';
    text += stored.length ? `Loaded bank has memories ${stored.join(', ')}. ` : 'No bank loaded (Memory space). ';
    text += reset ? 'Reset + groove creates neutral patterns; no backup is needed.' : missing.length ? `Preserve needs a local copy of memories ${missing.join(', ')}: open a bank that contains them, or choose Reset + groove.` : 'Preserve keeps notes, Predictability, motion and every other parameter.';
    $('#groove-scope').textContent = text;
  }
  async function loadMovement() {
    if (!S.catalog) {
      S.catalog = await get('/api/grooves');
      const options = $('#groove-options');
      options.replaceChildren(...S.catalog.templates.map((t) => h('option', { value: `${t.id} · ${t.name}` })));
      const byLabel = new Map(S.catalog.templates.map((t) => [`${t.id} · ${t.name}`, t]));
      S.catalog.byLabel = byLabel;
      $('#groove-parts').replaceChildren(...Array.from({ length: 10 }, (_, i) => {
        const input = h('input', { type: 'text', list: 'groove-options', placeholder: 'keep existing / straight after reset', 'aria-label': `Groove template for part ${i + 1}`, dataset: { part: i + 1 } });
        const curve = h('div', { class: 'curve', 'aria-hidden': 'true' });
        input.addEventListener('input', () => {
          const t = byLabel.get(input.value);
          curve.replaceChildren(...(t ? t.microtiming.map((v) => h('i', { class: v < 0 ? 'neg' : '', style: { height: `${Math.max(1, Math.abs(v) * 2)}px` }, title: String(v) })) : []));
          grooveChanged();
        });
        return h('div', { class: 'part' }, h('strong', {}, `Part ${fmt.slot(i + 1)}`), input, curve);
      }));
      $('#groove-memories').replaceChildren();
      memoryBoxes($('#groove-memories'), grooveChanged);
      setMemories($('#groove-memories'), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
      minute(`Groove catalog: ${S.catalog.profiles} timing profiles, ${S.catalog.aliases} named templates.`);
      drawCatalogue();
    }
    if (!S.bank) { const { bank } = await get('/api/patterns'); S.bank = bank; }
    updateGrooveScope();
  }
  $('#groove-all').addEventListener('click', () => { setMemories($('#groove-memories'), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]); grooveChanged(); });
  $('#groove-none').addEventListener('click', () => { setMemories($('#groove-memories'), []); grooveChanged(); });
  $$('input[name="groove-mode"]').forEach((r) => r.addEventListener('change', grooveChanged));
  function grooveSourceChanged() {
    const current = $('#groove-source').value === 'current';
    $('#groove-destination-row').hidden = !current;
    for (const box of $$('#groove-memories input')) box.disabled = current;
    $('#groove-all').disabled = current;
    $('#groove-none').disabled = current;
    if (current) { const destination = Number($('#groove-destination').value); setMemories($('#groove-memories'), destination ? [destination] : []); }
    grooveChanged();
  }
  $('#groove-source').addEventListener('change', grooveSourceChanged);
  $('#groove-destination').addEventListener('change', grooveSourceChanged);
  function grooveRequest() {
    const assignments = {};
    for (const input of $$('#groove-parts input')) {
      if (!input.value.trim()) continue;
      const t = S.catalog.byLabel.get(input.value);
      if (!t) { input.focus(); throw new Error(`Part ${input.dataset.part}: choose a template from the matching results.`); }
      assignments[input.dataset.part] = t.id;
    }
    const values = memoryValues($('#groove-memories'));
    const reset = $('input[name="groove-mode"]:checked').value === 'reset';
    const current = $('#groove-source').value === 'current';
    return { reset, slots: slotsText(values), assignments, name: $('#groove-name').value,
      current, destination: current ? Number($('#groove-destination').value) : null };
  }
  $('#groove-preview').addEventListener('click', () => attempt(async () => {
    const plan = await post('/api/grooves/plan', grooveRequest());
    await ask({ title: 'Groove change plan', wide: true, body: [
      h('p', {}, `Memories: ${plan.slots.join(', ')} · ${plan.mode}. Saving creates a new bank; sending replaces the complete selected memories.`),
      h('ul', {}, plan.assignments.map((a) => h('li', {}, `Part ${a.part}: ${a.template}`))),
      h('p', {}, plan.original_backup_available ? 'The complete source bank will be saved as a rollback copy.' : 'No original pattern backup is available.'),
      plan.unbacked_slots.length ? h('p', {}, `No original copy of destination memories ${plan.unbacked_slots.join(', ')}.`) : null],
      actions: [{ label: 'Close', value: '', default: true }] });
  }));
  $('#groove-save').addEventListener('click', () => attempt(async () => {
    const request = grooveRequest();
    const result = await post('/api/grooves/save', request);
    groove.dirty = false;
    groove.saved = result;
    $('#groove-send').disabled = false;
    const plan = result.plan;
    $('#groove-status').textContent = `Saved offline: ${result.name} · memories ${plan.slots.join(', ')} · ${plan.mode}. Next: choose the output in Connections, then send. Complete memories will be replaced.` + (result.rollback ? ` Original copy: ${result.rollback.split(/[\\/]/).pop()}.` : '');
    minute(`Groove bank ${result.name} saved (${plan.changed_bytes} bytes changed). Nothing sent.`, 'good');
    if (plan.unbacked_slots.length) minute(`No original copy for memories ${plan.unbacked_slots.join(', ')}.`);
    S.bank = (await get('/api/patterns')).bank;
    if (request.current) {
      $('#groove-source').value = 'stored';
      $('#groove-destination-row').hidden = true;
      for (const box of $$('#groove-memories input')) box.disabled = false;
      $('#groove-all').disabled = false;
      $('#groove-none').disabled = false;
      setMemories($('#groove-memories'), [request.destination]);
      updateGrooveScope();
    }
    celebrate('groove');
  }));
  $('#groove-send').addEventListener('click', () => { if (!groove.dirty) runJob(afterDevices(() => post('/api/grooves/send'))); });

  function drawCatalogue() {
    if (!S.catalog) return;
    const category = $('#catalog-category').value;
    const search = $('#catalog-search').value.trim().toLocaleLowerCase();
    const profiles = S.catalog.grouped_profiles.filter((profile) => profile.aliases.some((alias) =>
      (category === 'all' || alias.category === category) && `${alias.id} ${alias.name} ${profile.id}`.toLocaleLowerCase().includes(search)));
    const select = $('#catalog-profile');
    const previous = select.value;
    select.replaceChildren(...profiles.map((profile) => h('option', { value: profile.id }, `${profile.name} · ${profile.alias_count} source names`)));
    if (profiles.some((profile) => profile.id === previous)) select.value = previous;
    drawCatalogueAliases();
  }
  function drawCatalogueAliases() {
    const profile = S.catalog.grouped_profiles.find((item) => item.id === $('#catalog-profile').value);
    const previous = $('#catalog-alias').value;
    const category = $('#catalog-category').value;
    const search = $('#catalog-search').value.trim().toLocaleLowerCase();
    const matching = profile ? profile.aliases.filter((alias) => (category === 'all' || alias.category === category) &&
      `${alias.id} ${alias.name} ${profile.id}`.toLocaleLowerCase().includes(search)) : [];
    $('#catalog-alias').replaceChildren(...(profile ? profile.aliases.map((alias) => h('option', { value: alias.id }, alias.name)) : []));
    const selected = matching.find((alias) => alias.id.toLocaleLowerCase() === search)
      || matching.find((alias) => alias.id === previous) || matching[0];
    if (selected) $('#catalog-alias').value = selected.id;
    drawCatalogueSteps();
  }
  function drawCatalogueSteps() {
    const template = S.catalog.templates.find((item) => item.id === $('#catalog-alias').value);
    $('#catalog-steps tbody').replaceChildren(...(template ? template.steps.map((step) => h('tr', {},
      h('td', {}, step.step), h('td', {}, step.microtiming), h('td', {}, step.source))) : []));
    $('#catalog-description').textContent = template ? `${template.id} · ${template.category} · ${template.measured} measured / ${template.reconstructed} reconstructed steps. One microstep = 1/32 step; SWING 0 reference.` : 'No matching profiles.';
    $('#catalog-provenance').textContent = template ? JSON.stringify({ ...template.provenance,
      exact_microtiming: template.exact_microtiming_strings,
      source: S.catalog.sources[template.provenance.source] }, null, 2) : '';
  }
  $('#catalog-category').addEventListener('change', drawCatalogue);
  $('#catalog-search').addEventListener('input', drawCatalogue);
  $('#catalog-profile').addEventListener('change', drawCatalogueAliases);
  $('#catalog-alias').addEventListener('change', drawCatalogueSteps);
  $('#catalog-use').addEventListener('click', () => {
    const template = S.catalog && S.catalog.templates.find((item) => item.id === $('#catalog-alias').value);
    if (!template) return;
    const input = $(`#groove-parts input[data-part="${$('#catalog-part').value}"]`);
    input.value = `${template.id} · ${template.name}`;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
    minute(`Part ${$('#catalog-part').value}: ${template.name}. Review and save the bank before sending.`);
  });

  // ------------------------------------------------------------------ firmware
  let firmwarePick = null;
  let firmwareListingRequest = 0;
  async function loadFirmware() {
    const request = ++firmwareListingRequest;
    const { entries, error } = await get('/api/firmware');
    if (request !== firmwareListingRequest) return;
    S.firmware = entries;
    if (error) minute(`Firmware archive: ${error}`, 'error');
    const list = $('#firmware-list');
    list.replaceChildren(...(entries.length ? entries.map((entry, i) => {
      const row = h('div', { class: 'item', role: 'option', tabindex: '-1', 'aria-selected': firmwarePick === entry.id ? 'true' : 'false' },
        h('span', { class: 'slot' }, entry.installable ? (entry.experimental ? 'EXP' : 'OK') : 'ARC'),
        h('span', { class: 'name' }, `${entry.name} ${entry.version}`, h('span', { class: 'group' }, entry.status)),
        h('span', { class: 'meta' }, entry.sha256.slice(0, 10)));
      row.addEventListener('click', () => { firmwarePick = entry.id; loadFirmwareDetail(); });
      return row;
    }) : [h('div', { class: 'empty' }, 'The archive is empty. Add the Korg volca sample 1.42 updater you downloaded; the Browser App builds DataBeat OS from it.')]));
    loadFirmwareDetail();
  }
  function loadFirmwareDetail() {
    const entry = S.firmware.find((e) => e.id === firmwarePick);
    $$('#firmware-list .item').forEach((row, i) => row.setAttribute('aria-selected', S.firmware[i] && S.firmware[i].id === firmwarePick ? 'true' : 'false'));
    $('#firmware-detail').textContent = entry ? [
      `${entry.name} ${entry.version}`,
      `Status: ${entry.status}${entry.installable ? '' : ' — archive only, cannot be installed'}${entry.experimental ? ' — experimental' : ''}`,
      `Hardware tested: ${entry.hardware_tested ? 'yes' : 'no'}`,
      `SHA-256: ${entry.sha256}`, `Duration: ${entry.seconds.toFixed(1)} s`,
      `Provenance: ${typeof entry.provenance === 'string' ? entry.provenance : JSON.stringify(entry.provenance)}`].join('\n') : 'Select an archived image.';
    $('#firmware-send').disabled = !(entry && entry.installable && !entry.experimental);
  }
  $('#firmware-refresh').addEventListener('click', () => attempt(loadFirmware));
  $('#firmware-send').addEventListener('click', () => {
    const entry = S.firmware.find((e) => e.id === firmwarePick);
    if (!entry) return;
    runJob(afterDevices(() => post('/api/firmware/send', { id: entry.id })));
  });
  $('#korg-file').addEventListener('change', (event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    attempt(async () => {
      operation.show('Building DataBeat OS', 'Checking the Korg updater and building DataBeat OS on this computer…');
      try {
        const { entries } = await api('PUT', '/api/firmware/korg', file, { headers: { 'X-WMC-Name': q(file.name) } });
        minute(`${entries[0].name} ${entries[0].version} built from your Korg updater. Studio checked the result.`, 'good');
        firmwarePick = entries[0].id;
      } finally { operation.hide(); }
      await loadFirmware();
    });
  });

  // ------------------------------------------------------------------ connections
  async function loadDevices(refresh = false) {
    const devices = refresh ? await post('/api/devices/refresh') : await get('/api/devices');
    S.devices = devices;
    const fill = (select, list, selected, label) => {
      select.replaceChildren(h('option', { value: '' }, `— choose the ${label} —`), ...list.map((d) => (typeof d === 'string'
        ? h('option', { value: d }, d) : h('option', { value: d.key }, `${d.name} · ${d.api}`))));
      if (selected && !list.some((d) => (typeof d === 'string' ? d : d.key) === selected)) {
        select.append(h('option', { value: selected }, `${selected.split('::').pop()} (not connected)`));
      }
      select.value = selected || '';
    };
    fill($('#device-output'), devices.outputs, devices.selected.output, 'output');
    fill($('#device-input'), devices.inputs, devices.selected.input, 'input');
    fill($('#device-midi'), devices.midi, devices.selected.midi, 'MIDI output');
    const status = [
      ['Transfer output', devices.selected.output, devices.connected.output],
      ['Backup input', devices.selected.input, devices.connected.input],
      ['MIDI output', devices.selected.midi, devices.connected.midi]];
    $('#device-status').replaceChildren(...[...status.map(([label, value, ok]) => h('li', {}, h('span', { class: `dot ${value ? (ok ? 'ok' : 'bad') : ''}` }),
      `${label}: ${value ? (ok ? value.split('::').pop() : `${value.split('::').pop()} — not connected`) : 'not chosen'}`)),
      ...Object.values(devices.errors).map((e) => h('li', { class: 'hint' }, e)),
      !devices.outputs.length && !devices.errors.audio ? h('li', { class: 'hint' }, 'No audio outputs found. Connect your audio interface or headphone adapter, then press Refresh devices.') : null].filter(Boolean));
    const chip = $('#connection-chip');
    const output = devices.outputs.find((d) => d.key === devices.selected.output);
    chip.textContent = output ? `Output: ${output.name}` : devices.selected.output ? 'Output: disconnected' : 'Output: not chosen';
    chip.classList.toggle('ok', !!output);
    chip.classList.toggle('warn', !output);
  }
  // A device choice is stored by an asynchronous request. Actions that need a
  // chosen device wait for the latest choice to be stored before starting,
  // so a quick Send after choosing an output does not fail as "not chosen".
  let deviceSelection = Promise.resolve();
  const afterDevices = (start) => deviceSelection.then(start);
  for (const [id, key] of [['#device-output', 'output'], ['#device-input', 'input'], ['#device-midi', 'midi']]) {
    $(id).addEventListener('change', () => attempt(async () => {
      const stored = post('/api/devices/select', { [key]: $(id).value || null });
      deviceSelection = stored.catch(() => null);
      await stored;
      await loadDevices();
      minute(`${{ output: 'Transfer output', input: 'Backup input', midi: 'MIDI output' }[key]}: ${$(id).value ? $(id).value.split('::').pop() : 'not chosen'}.`);
    }));
  }
  $('#devices-refresh').addEventListener('click', () => attempt(() => loadDevices(true)));
  $('#linux-menu').addEventListener('click', () => attempt(async () => {
    const result = await post('/api/system/linux-menu');
    minute(`Added to the applications menu: ${result.path}`, 'good');
  }));

  $('#system-check').addEventListener('click', () => attempt(async () => {
    const report = await get('/api/system/status');
    $('#system-report').textContent = `Studio ${report.version} · ${report.platform}\n` +
      report.checks.map((item) => `${item.available ? 'OK' : 'MISSING'}  ${item.name}: ${item.detail}`).join('\n') +
      '\n\n' + Object.entries(report.paths).map(([name, path]) => `${name}: ${path}`).join('\n') +
      '\n\nNo audio or MIDI devices were opened.';
  }));

  // ------------------------------------------------------------------ global keys, close, heartbeat
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (!$('#space-gathering').hidden) saveKit();
    }
  });
  $('#close-button').addEventListener('click', () => attempt(async () => {
    const answer = await ask({ title: 'Close the Browser App?', body: 'The local helper stops. Your kits, banks and workbench are kept. Open VolcaStudio XL Browser App again to continue.',
      actions: [{ label: 'Stay', value: '', default: true }, { label: 'Close Browser App', value: 'yes', kind: 'primary' }] });
    if (answer !== 'yes') return;
    await post('/api/shutdown');
    session.closed = true;
    sessionLost('The Browser App is closed. You can close this window. Your work is kept for next time.');
    $('#main').setAttribute('inert', '');
    $('.spaces').setAttribute('inert', '');
  }));
  setInterval(() => { if (!session.closed && session.token) post('/api/heartbeat').catch(() => {}); }, 20000);
  addEventListener('pagehide', () => { if (session.token && !session.closed) navigator.sendBeacon('/api/bye', new Blob([session.token], { type: 'text/plain' })); });

  // ------------------------------------------------------------------ start
  async function start() {
    document.querySelectorAll('[data-pixel]').forEach((el) => el.append(pixel(el.dataset.pixel)));
    $('#motion-toggle').checked = motion.on;
    motion.set(motion.on);
    $('#motion-toggle').addEventListener('change', (event) => motion.set(event.target.checked));
    if (session.code) {
      // Exchange the single-use launch code for this session's private token.
      try {
        const response = await fetch('/api/session/claim', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: session.code }), cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) { sessionLost(data.error || 'This Browser App link has expired. Open VolcaStudio XL Browser App again.'); return; }
        session.token = data.token;
        sessionStorage.setItem('wmc-token', data.token);
      } catch (error) {
        sessionLost('The Browser App’s helper is not answering. Open VolcaStudio XL Browser App again.');
        return;
      }
    }
    if (!session.token) {
      sessionLost('Open the Browser App with the “VolcaStudio XL Browser App” application. It starts the local helper and opens this page with a private key.');
      return;
    }
    if (session.browser === 'other' || !/Chrome\//.test(navigator.userAgent)) {
      const notice = $('#session-notice');
      notice.replaceChildren('Google Chrome was not found, so the Browser App opened in another browser. It is designed and tested for Chrome: install it from ',
        h('a', { href: 'https://www.google.com/chrome/', target: '_blank', rel: 'noopener' }, 'google.com/chrome'), ', then open VolcaStudio XL Browser App again. You can continue here, but it is not a supported setup.');
      notice.hidden = false;
    }
    const state = await attempt(() => get('/api/state'));
    if (!state) return;
    $('#storage-info').textContent = `Browser App ${state.wmc_version} · shared backend ${state.backend_version}. Kits: ${state.storage.kits} · Banks: ${state.storage.patterns} · Browser App copies: ${state.storage.wmc}` + (state.bench ? ' · BENCH MODE: simulated devices, temporary storage.' : '');
    if (state.bench) sessionLost('Bench mode: simulated devices and temporary storage. Nothing here reaches a real Volca.');
    $('#linux-menu-row').hidden = !state.linux_menu;
    const preferences = await get('/api/preferences');
    $('#autoplay').checked = preferences.autoplay === true;
    $('#preview-mode').value = preferences.preview_mode || 'volca';
    await attempt(async () => setDraft(await get('/api/draft')));
    await attempt(() => loadLibraries());
    await attempt(() => loadDevices());
    minute('Welcome. Choose samples in Gathering or open a saved kit in Commons.');
    let space = 'gathering';
    try { space = sessionStorage.getItem('wmc-space') || space; } catch (e) { /* ignore */ }
    go($(`#space-${space}`) ? space : 'gathering');
    if (state.job && state.job.state !== 'finished') {
      minute(`An operation is still running: ${state.job.title}.`);
      runJob(Promise.resolve(state.job));
    }
  }
  start();
})();
