// DUBBE pages work without JavaScript; this only makes three things smoother.

// 1. Review editor: a click on a timeline block (report.timeline_html writes the number into #seg_pick input)
//    opens that sentence below the video.
const pick = document.querySelector('#seg_pick input');
if (pick) pick.addEventListener('input', () => {
  const d = document.getElementById('s' + pick.value);
  if (d) { d.open = true; d.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
});

// 2. Review editor: save text, tags and ratings without reloading, so the video keeps its place.
//    Forms marked data-autosave (speaker name and voice) save on every change, so several rows can be changed in a row.
document.querySelectorAll('form.ajax').forEach(f => {
  f.addEventListener('submit', async e => {
    e.preventDefault();
    const out = f.querySelector('.saved');
    out.textContent = 'Saving…';
    try {
      const r = await fetch(f.action, {method: 'POST', body: new FormData(f), headers: {'X-Fetch': '1'}});
      out.textContent = r.ok ? 'Saved ✓' + (f.dataset.hint || '') : 'Not saved (error ' + r.status + ')';
    } catch { out.textContent = 'Not saved (no connection)'; }
  });
  if ('autosave' in f.dataset) {
    f.classList.add('autosaving');  // CSS hides the Save button: nothing to press
    f.addEventListener('change', () => f.requestSubmit());
  }
});

// 3. Upload areas: show the chosen file, highlight while dragging, and the file's length vs. the minutes left.
document.querySelectorAll('[data-drop]').forEach(zone => {
  const input = zone.querySelector('input[type=file]'), title = zone.querySelector('[data-drop-title]');
  const info = zone.querySelector('[data-drop-info]'), dur = document.getElementById('dur');
  const first = [title.textContent, info.textContent];
  ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, () => zone.classList.add('over')));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, () => zone.classList.remove('over')));
  const link = zone.closest('form')?.querySelector('[data-link]');
  link?.addEventListener('input', () => {  // a link instead of a file: one or the other is sent
    input.required = !link.value.trim();
    if (link.value.trim() && input.files.length) { input.value = ''; input.dispatchEvent(new Event('change')); }
  });
  input.addEventListener('change', () => {
    const f = input.files[0];
    if (f && link) { link.value = ''; input.required = true; }
    zone.classList.toggle('has-file', !!f);
    [title.textContent, info.textContent] = f ? [f.name, `${(f.size / 1048576).toFixed(1)} MB · click or drop to change`] : first;
    zone.querySelector('.pick').textContent = f ? 'Change file' : 'Choose file';
    if (!f || !dur) return;
    dur.textContent = 'Reading the length…'; dur.classList.remove('warn');
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.onloadedmetadata = () => {
      const min = v.duration / 60, left = parseFloat(input.dataset.left);
      dur.textContent = `Length ${min.toFixed(1)} min · ${left} min left this month` + (min > left ? ' — not enough minutes for this file.' : '');
      dur.classList.toggle('warn', min > left);
      URL.revokeObjectURL(v.src);
    };
    v.onerror = () => { dur.textContent = 'The browser cannot read this file’s length; the server will check it.'; };
    v.src = URL.createObjectURL(f);
  });
});

// Picture slow-down slider: show "off" or the allowed factor.
document.querySelectorAll('[data-slow]').forEach(r => {
  const out = r.closest('label').querySelector('[data-slow-out]');
  const upd = () => { out.textContent = r.value == 1 ? 'off' : `up to ${(+r.value).toFixed(2)}×`; };
  r.addEventListener('input', upd); upd();
});

// ---- motion and media on the public pages (all of it stops for prefers-reduced-motion) ----
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Scroll reveals: once, with children of [data-stagger] 70 ms apart.
document.querySelectorAll('[data-stagger]').forEach(g =>
  g.querySelectorAll(':scope > [data-reveal]').forEach((el, i) => el.style.transitionDelay = (i * 70) + 'ms'));
const seen = new IntersectionObserver(entries => entries.forEach(e => {
  if (!e.isIntersecting) return;
  e.target.classList.add('in');
  e.target.querySelectorAll('.tl').forEach(tl => tl.classList.add('tl-in'));  // timeline blocks grow in
  e.target.querySelectorAll('[data-odometer]').forEach(odometer);              // numbers roll in
  seen.unobserve(e.target);
}), {rootMargin: '0px 0px -60px 0px'});
document.querySelectorAll('[data-reveal]').forEach(el => calm ? el.classList.add('in') : seen.observe(el));
document.querySelectorAll('.demo-body .tl-b, .showcase-body .tl-b').forEach((b, i) => b.style.setProperty('--i', Math.min(i, 20)));

// Rolling digits (after motion.dev's AnimateNumber): each digit is a 0-9 strip moved to its value.
function odometer(el) {
  const text = el.textContent;
  el.removeAttribute('data-odometer');
  el.innerHTML = `<span class="sr">${text}</span><span aria-hidden="true"></span>`;
  const shown = el.lastChild;
  for (const ch of text) {
    if (!/\d/.test(ch)) { shown.append(ch); continue; }
    const box = document.createElement('span'), strip = document.createElement('span');
    box.className = 'odo';
    strip.innerHTML = [...'0123456789'].map(d => `<span>${d}</span>`).join('');
    box.append(strip); shown.append(box);
    requestAnimationFrame(() => requestAnimationFrame(() => strip.style.transform = `translateY(-${ch}em)`));
  }
}

// One audio player for voice orbs and sentence cards: press again to stop.
const player = new Audio();
let playingBtn = null;
const stop = () => { if (playingBtn) playingBtn.classList.remove('playing'); playingBtn = null; };
player.addEventListener('ended', stop);
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-play]');
  if (!btn) return;
  const again = btn === playingBtn;
  player.pause(); stop();
  if (again) return;
  player.src = btn.dataset.play;
  player.play().then(() => { playingBtn = btn; btn.classList.add('playing'); }).catch(stop);
});

// Carousels: arrow buttons move one card; [data-autoplay] advances every 5 s until the visitor touches it.
document.querySelectorAll('[data-carousel]').forEach(c => {
  const track = c.querySelector('.track');
  const step = dir => {
    const card = track.firstElementChild;
    const w = card ? card.getBoundingClientRect().width + 20 : 300;
    const end = track.scrollLeft + track.clientWidth >= track.scrollWidth - 4;
    track.scrollTo({left: dir > 0 && end ? 0 : track.scrollLeft + dir * w, behavior: calm ? 'auto' : 'smooth'});
  };
  c.querySelector('[data-prev]')?.addEventListener('click', () => step(-1));
  c.querySelector('[data-next]')?.addEventListener('click', () => step(1));
  if (c.hasAttribute('data-autoplay') && !calm) {
    const timer = setInterval(() => { if (!document.hidden && c.closest('.in')) step(1); }, 5000);
    const quit = () => clearInterval(timer);
    ['pointerdown', 'wheel', 'focusin', 'keydown'].forEach(ev => c.addEventListener(ev, quit, {once: true}));
  }
});

// Tabs (the hero panel): click or arrow keys; switching stops any sound or video.
document.querySelectorAll('[role=tablist]').forEach(list => {
  const tabs = [...list.querySelectorAll('[role=tab]')];
  const show = t => {
    tabs.forEach(x => {
      const on = x === t;
      x.classList.toggle('on', on); x.setAttribute('aria-selected', on); x.tabIndex = on ? 0 : -1;
      document.getElementById(x.getAttribute('aria-controls')).hidden = !on;
    });
    player.pause(); stop(); document.querySelectorAll('video').forEach(v => v.pause());
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => show(t));
    t.addEventListener('keydown', e => {
      const d = {ArrowRight: 1, ArrowLeft: -1}[e.key];
      if (d) { const n = tabs[(i + d + tabs.length) % tabs.length]; show(n); n.focus(); }
    });
  });
});

// Voice orbs, centre-focused (after elevenlabs.io): arrows, keys, swipe, or click a side orb to bring it forward.
document.querySelectorAll('[data-coverflow]').forEach(cf => {
  const items = [...cf.querySelectorAll('.cf-item')], n = items.length;
  let at = Math.max(0, items.findIndex(it => it.hasAttribute('data-default'))), swiped = false;
  const layout = () => {
    const w = cf.clientWidth, near = Math.min(310, w * .27), far = Math.min(540, w * .46);
    items.forEach((it, i) => {
      let d = i - at;
      if (d > n / 2) d -= n;
      if (d < -n / 2) d += n;  // endless: the far side wraps around
      const a = Math.abs(d);
      it.style.setProperty('--x', Math.sign(d) * [0, near, far][Math.min(a, 2)] + 'px');
      it.style.setProperty('--s', [1, .78, .56][a] ?? .4);
      it.style.setProperty('--o', [1, 1, .45][a] ?? 0);
      it.style.setProperty('--co', a < 2 ? 1 : 0);
      it.classList.toggle('on', a === 0);
      it.classList.toggle('vis', a < 3);
    });
  };
  const go = i => { if (n < 2) return; at = (i + n) % n; player.pause(); stop(); layout(); };
  cf.querySelector('[data-prev]').addEventListener('click', () => go(at - 1));
  cf.querySelector('[data-next]').addEventListener('click', () => go(at + 1));
  items.forEach((it, i) => it.addEventListener('click', e => {
    if (i !== at || swiped) { e.stopPropagation(); e.preventDefault(); swiped = false; if (i !== at) go(i); }
  }, true));
  cf.addEventListener('keydown', e => { if (e.key === 'ArrowRight') go(at + 1); if (e.key === 'ArrowLeft') go(at - 1); });
  let x0 = null;
  cf.addEventListener('pointerdown', e => { x0 = e.clientX; });
  cf.addEventListener('pointerup', e => {
    if (x0 !== null && Math.abs(e.clientX - x0) > 40) { swiped = true; go(at + (e.clientX < x0 ? 1 : -1)); }
    x0 = null;
  });
  new ResizeObserver(layout).observe(cf);
  layout();
});

// Subtitle typewriter (after motion.dev's Typewriter): types the original line, then the dub line.
document.querySelectorAll('[data-type]').forEach(el => {
  const lines = JSON.parse(el.dataset.type);
  if (!lines.length) return;
  if (calm) { el.textContent = lines[lines.length - 1]; return; }
  let li = 0, ci = 0, back = false;
  const tick = () => {
    const line = lines[li];
    el.textContent = line.slice(0, ci) || ' ';
    if (!back && ci < line.length) { ci++; setTimeout(tick, 55); }
    else if (!back) { back = true; setTimeout(tick, 2000); }
    else if (ci > 0) { ci--; setTimeout(tick, 15); }
    else { back = false; li = (li + 1) % lines.length; setTimeout(tick, 350); }
  };
  tick();
});

// A real correction, scrambled from the wrong word to the right one and back (after motion.dev's ScrambleText).
function scramble(el, to, ok) {
  const len = Math.max(el.textContent.length, to.length), abc = 'abcdefghijklmnopqrstuvwxyz';
  let frame = 0;
  const run = () => {
    frame++;
    el.textContent = [...Array(len)].map((_, i) => i < frame / 3 ? (to[i] || '') : abc[Math.floor(Math.random() * 26)]).join('');
    if (frame / 3 < len) requestAnimationFrame(run); else { el.textContent = to; el.classList.toggle('done', ok); }
  };
  run();
}
document.querySelectorAll('[data-scramble]').forEach(el => {
  const wrong = el.textContent, right = el.dataset.scramble;
  if (calm) { el.textContent = right; el.classList.add('done'); return; }
  setTimeout(() => scramble(el, right, true), 1500);
  setInterval(() => el.textContent === right ? scramble(el, wrong, false) : scramble(el, right, true), 3500);
});

// Course cost calculator (after upwork.com's estimate). Rates: measured 29 s (into English) to 77 s (into Korean) per video minute,
// GPU $0.35/hour (assumption), ElevenLabs $0.50-0.60/min, human dubbing $80-250/min (unverified figure).
document.querySelectorAll('[data-calc]').forEach(c => {
  const r = c.querySelector('input[type=range]'), out = k => c.querySelector(`[data-out=${k}]`);
  const money = v => v < 10 ? v.toFixed(2) : Math.round(v).toLocaleString('en-US');
  const span = ([a, b]) => `$${money(a)}–${money(b)}`;
  const upd = () => {
    const m = +r.value, s = [m * 29, m * 77];
    out('min').textContent = m.toLocaleString('en-US');
    out('time').textContent = s[1] < 3600 ? `${Math.round(s[0] / 60)}–${Math.round(s[1] / 60)} min`
                                           : `${(s[0] / 3600).toFixed(1)}–${(s[1] / 3600).toFixed(1)} h`;
    const cost = {ours: s.map(x => x / 3600 * .35), el: [m * .5, m * .6], human: [m * 80, m * 250]};
    const top = Math.log10(cost.human[1] + 1);
    Object.entries(cost).forEach(([k, v]) => {
      out(k).textContent = span(v);
      c.querySelector(`[data-bar=${k}]`).style.width = Math.max(2, 100 * Math.log10(v[1] + 1) / top) + '%';
    });
  };
  r.addEventListener('input', upd);
  upd();
});

// ---- tools ----
// Character counters for the tool text boxes.
document.querySelectorAll('.tool textarea').forEach(ta => {
  const count = ta.form.querySelector('[data-count]');
  const upd = () => { if (count) count.textContent = ta.value.length.toLocaleString('en-US'); };
  ta.addEventListener('input', upd); upd();
});

// Text to speech: tag chips insert at the cursor; the preview shows tags as pills, like comments in the text.
document.querySelectorAll('[data-tts]').forEach(form => {
  const ta = form.querySelector('textarea'), preview = form.querySelector('[data-preview]'), tagcount = form.querySelector('[data-tagcount]');
  const known = new Set([...form.querySelectorAll('[data-insert]')].map(b => b.dataset.insert.slice(1, -1)));
  const vocal = new Set([...form.querySelectorAll('.tagchip.vocal')].map(b => b.dataset.insert.slice(1, -1)));
  const esc = s => s.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const render = () => {
    let n = 0;
    preview.innerHTML = esc(ta.value).replace(/\[([a-z]+)\]/g, (m, t) => {
      n++;
      return `<span class="tagpill ${known.has(t) ? (vocal.has(t) ? 'vocal' : '') : 'bad'}">[${t}]</span>`;
    }).replace(/\n/g, '<br>');
    if (!ta.value.trim()) preview.innerHTML = '';
    tagcount.textContent = n ? `${n} tag${n > 1 ? 's' : ''}` : '';
  };
  form.querySelectorAll('[data-insert]').forEach(b => b.addEventListener('click', () => {
    const tag = b.dataset.insert + ' ', s = ta.selectionStart ?? ta.value.length;
    ta.setRangeText(tag, s, ta.selectionEnd ?? s, 'end');
    ta.focus(); ta.dispatchEvent(new Event('input'));
  }));
  ta.addEventListener('input', render); render();

  // only the voices of the chosen language; "hear this voice" plays the chosen one
  const lang = form.querySelector('[data-lang]'), voice = form.querySelector('[data-voice]'), hear = form.querySelector('[data-sample-btn]');
  const sync = () => {
    const noclone = voice.dataset.noclone.split(' ').includes(lang.value);  // e.g. Kazakh: its voice cannot speak from a recording
    [...voice.options].forEach(o => { o.hidden = o.dataset.lang !== lang.value && (o.dataset.lang !== 'any' || noclone); });
    if (voice.selectedOptions[0]?.hidden) voice.value = [...voice.options].find(o => !o.hidden)?.value;
    const s = voice.selectedOptions[0]?.dataset.sample;
    hear.hidden = !s; if (s) hear.dataset.play = s;
  };
  lang.addEventListener('change', sync); voice.addEventListener('change', sync); sync();
});

// Uploads over 8 MB go up in 8 MB pieces first (the public dev tunnel refuses requests over 10-20 MB with 413); the
// form is then sent with an empty stand-in file of the same name and the upload id (app.py: upload_part, chunked).
const PART = 8 * 1024 * 1024;
document.querySelectorAll('form[enctype="multipart/form-data"]:not([data-recorder])').forEach(form => form.addEventListener('submit', async e => {
  const input = form.querySelector('input[type=file]'), f = input && input.files[0];
  if (!f || f.size <= PART) return;
  e.preventDefault();
  const id = [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
  const btn = form.querySelector('button:not([type=button])'), label = btn && btn.textContent;
  if (btn) btn.disabled = true;
  for (let at = 0; at < f.size; at += PART) {
    if (btn) btn.textContent = `Uploading ${Math.floor(100 * at / f.size)} %`;
    const r = await fetch(`/app/upload/${id}?at=${at}`, {method: 'POST', body: f.slice(at, at + PART)});
    if (!r.ok) {
      if (btn) { btn.textContent = label; btn.disabled = false; }
      alert(await r.text());
      return;
    }
  }
  const dt = new DataTransfer();
  dt.items.add(new File([], f.name, {type: f.type}));
  input.files = dt.files;
  const hidden = Object.assign(document.createElement('input'), {type: 'hidden', name: 'upload', value: id});
  form.append(hidden);
  if (btn) btn.textContent = 'Starting…';
  form.submit();  // the native submit: no second pass through this handler
}));

// Translate: swap the two languages.
document.querySelectorAll('[data-swap]').forEach(b => b.addEventListener('click', () => {
  const f = b.form, a = f.querySelector('[data-src]'), z = f.querySelector('[data-tgt]');
  [a.value, z.value] = [z.value, a.value];
  z.dispatchEvent(new Event('change'));  // the voice list follows the target language
}));

// Dub a video: voices of the target language (clones speak both); "Hear" plays the chosen one's sample.
document.querySelectorAll('[data-voice-pick]').forEach(sel => {
  const tgt = sel.form.querySelector('[data-tgt]'), hear = sel.form.querySelector('[data-voice-hear]');
  const sync = () => {
    const noclone = sel.dataset.noclone.split(' ').includes(tgt.value);
    [...sel.options].forEach(o => { if (o.dataset.lang) o.hidden = o.disabled = o.dataset.lang !== tgt.value && (o.dataset.lang !== 'any' || noclone); });
    if (sel.selectedOptions[0]?.hidden) sel.value = '';  // a preset of the other language: back to automatic
    const s = sel.selectedOptions[0]?.dataset.sample;
    hear.hidden = !s;
    if (s) hear.dataset.play = s;
  };
  tgt.addEventListener('change', sync);
  sel.addEventListener('change', sync);
  sync();
});

// Copy a result to the clipboard.
document.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', async () => {
  await navigator.clipboard.writeText(b.dataset.copy);
  b.textContent = 'Copied ✓';
}));

// Clone my voice: record the shown sentences live (no file upload), listen back, then send it with the consent boxes.
document.querySelectorAll('form[data-recorder]').forEach(form => {
  const rec = form.querySelector('[data-rec]'), stop = form.querySelector('[data-stop]'), time = form.querySelector('[data-time]');
  const playback = form.querySelector('[data-playback]'), msg = form.querySelector('[data-rec-msg]'), submit = form.querySelector('[data-submit]');
  let recorder, chunks = [], blob = null, started = 0, timer;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    msg.textContent = 'This browser cannot record from a microphone. Please use a current Chrome, Edge, Firefox or Safari.';
    rec.disabled = true;
    return;
  }
  rec.addEventListener('click', async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = e => chunks.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        blob = new Blob(chunks, {type: recorder.mimeType || 'audio/webm'});
        playback.src = URL.createObjectURL(blob); playback.hidden = false;
        const s = (Date.now() - started) / 1000;
        msg.textContent = s < 8 ? 'That was short — please read all three sentences (at least 8 seconds).' : 'Listen back; record again if needed.';
        submit.disabled = s < 8;
      };
      recorder.start();
      started = Date.now(); rec.disabled = true; stop.disabled = false; submit.disabled = true; msg.textContent = 'Recording…';
      timer = setInterval(() => {
        const s = Math.floor((Date.now() - started) / 1000);
        time.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
        if (s >= 60) stop.click();  // a minute is plenty
      }, 250);
    } catch (e) {
      msg.textContent = 'No microphone access: allow it in the browser and try again.';
    }
  });
  stop.addEventListener('click', () => {
    clearInterval(timer); recorder?.state === 'recording' && recorder.stop();
    rec.disabled = false; stop.disabled = true; rec.lastChild.textContent = 'Record again';
  });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!blob) return;
    const data = new FormData(form);
    data.append('file', blob, 'recording.' + (blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm'));
    submit.disabled = true; msg.textContent = 'Sending…';
    const r = await fetch(form.action, {method: 'POST', body: data});
    if (r.ok) { location.href = r.url; return; }
    msg.textContent = await r.text(); submit.disabled = false;
  });
});

// Account menu (top of the sidebar): closes on a click elsewhere or Escape.
const closeAcct = e => document.querySelectorAll('details[data-acct][open]').forEach(d => {
  if (e.type === 'keydown' ? e.key === 'Escape' : !d.contains(e.target)) d.open = false;
});
document.addEventListener('click', closeAcct);
document.addEventListener('keydown', closeAcct);

// A short message at the bottom right (same look as the ?m= notices).
const toast = text => {
  const t = Object.assign(document.createElement('p'), {className: 'notice toast', role: 'status', textContent: text});
  document.body.append(t);
  setTimeout(() => t.remove(), 5000);
};

// Marketplace "Get": add the voice without leaving the page; the button turns into "Open".
document.querySelectorAll('form[data-get]').forEach(f => f.addEventListener('submit', async e => {
  e.preventDefault();
  const btn = f.querySelector('button');
  btn.disabled = true;
  const r = await fetch(f.action, {method: 'POST', headers: {'x-fetch': '1'}});
  if (!r.ok) { btn.disabled = false; return; }
  const open = Object.assign(document.createElement('a'), {href: f.dataset.open, className: 'secondary got', textContent: 'Open'});
  open.setAttribute('role', 'button');
  f.replaceWith(open);
  toast(f.dataset.msg || 'Added to your voices');
}));

// Voice Studio: the listing preview follows the form as you type; counters; at most three tags.
document.querySelectorAll('form[data-studio]').forEach(form => {
  const outs = k => document.querySelectorAll(`[data-out="${k}"]`);
  const sync = () => {
    const d = new FormData(form), tags = d.getAll('tags');
    outs('name').forEach(e => { e.textContent = (d.get('name') || '').trim() || 'Your voice'; });
    outs('description').forEach(e => { e.textContent = (d.get('description') || '').trim() || 'Your description appears here.'; });
    outs('category').forEach(e => { e.textContent = d.get('category') || 'Category'; });
    outs('tags').forEach(e => e.replaceChildren(...tags.map(t => Object.assign(document.createElement('span'), {className: 'chip', textContent: t}))));
    form.querySelectorAll('[data-count]').forEach(c => {
      const k = c.dataset.count, field = form.querySelector(`[name="${k}"]`);
      const n = k === 'tags' ? tags.length : (field.value || '').length, max = k === 'tags' ? 3 : field.maxLength;
      c.textContent = `${n}/${max}`;
      c.classList.toggle('full', n >= max);
    });
    form.querySelectorAll('[data-max] input').forEach(i => { i.disabled = !i.checked && tags.length >= 3; });
  };
  form.addEventListener('input', sync);
  form.addEventListener('change', sync);
  sync();
});

// Ask before deleting.
document.querySelectorAll('form[data-confirm]').forEach(f => f.addEventListener('submit', e => {
  if (!confirm(f.dataset.confirm)) e.preventDefault();
}));

// Speaker detection: a transcript line or a click on the lanes plays the original from there; while it plays, the
// spoken line lights up (and stays in view) and a playhead runs over the lanes.
document.querySelectorAll('[data-spk-player]').forEach(v => {
  const root = v.closest('.spk-layout'), lanes = root.querySelector('.spk-lanes'), dur = parseFloat(v.dataset.duration) || 1;
  const rows = [...root.querySelectorAll('.tx-row[data-t]')];
  const seek = t => { player.pause(); stop(); v.currentTime = t; v.play(); };
  const editing = () => root.classList.contains('editing');  // fixing speakers: clicks belong to the editor
  rows.forEach(r => {
    r.addEventListener('click', () => { if (!editing()) seek(+r.dataset.t); });
    r.addEventListener('keydown', e => { if (!editing() && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); seek(+r.dataset.t); } });
  });
  root.querySelectorAll('.spk-lane-track').forEach(tr => tr.addEventListener('click', e => {
    const b = tr.getBoundingClientRect();
    seek(Math.max(0, Math.min(1, (e.clientX - b.left) / b.width)) * dur);
  }));
  let on = null;
  v.addEventListener('timeupdate', () => {
    const t = v.currentTime;
    lanes.style.setProperty('--p', Math.min(1, t / dur));
    lanes.classList.add('playing');
    const r = rows.find(r => t >= +r.dataset.t && t < +r.dataset.end) || null;
    if (r === on) return;
    on?.classList.remove('on');
    on = r;
    if (r) { r.classList.add('on'); if (!v.paused) r.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  });
});

// Speaker Detection - fix who said what, like trimming clips: in edit mode a handle between two lines moves words
// from one line to the other (drag it onto a word, or arrow keys), a word click plays from it or starts a new line
// there, and a line's name becomes a speaker list. Save sends every line back as speaker + word indices; the server
// checks that no word was lost or doubled.
document.querySelectorAll('[data-spk-editor]').forEach(root => {
  const tx = root.querySelector('.spk-tx'), editBtn = root.querySelector('[data-spk-edit]');
  const bar = root.querySelector('[data-edit-bar]'), help = root.querySelector('[data-edit-help]');
  const info = JSON.parse(root.querySelector('[data-spk-data]').textContent);
  const video = root.querySelector('[data-spk-player]');
  const color = id => id === 'new' ? '#8a8a8a' : info.colors[Math.max(0, info.speakers.indexOf(id)) % info.colors.length];
  const name = id => id === 'new' ? 'New speaker' : info.names[info.speakers.indexOf(id)] || id;
  const rows = () => [...tx.querySelectorAll('.tx-row')];
  const words = r => [...r.querySelectorAll('.w')];
  const clock = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  let menu = null;
  const changed = () => { bar.hidden = false; refresh(); };

  const setSpeaker = (r, id) => {
    r.dataset.spk = id;
    r.style.setProperty('--c', color(id));
    const sel = r.querySelector('.tx-name select');
    if (sel) sel.value = id; else r.querySelector('.tx-name').textContent = name(id);
  };
  // after a change: each line's time from its first word, "continued" lines, and the handles between lines
  const refresh = () => {
    rows().forEach((r, k, all) => {
      const ws = words(r);
      r.dataset.t = ws[0].dataset.s;
      r.querySelector('.tx-time').textContent = clock(+ws[0].dataset.s);
      r.classList.toggle('cont', k > 0 && all[k - 1].dataset.spk === r.dataset.spk);
    });
    tx.querySelectorAll('.tx-cut').forEach(h => h.remove());
    if (!root.classList.contains('editing')) return;
    rows().slice(1).forEach(r => {  // a word-high bar in front of each line's first word: where this line begins
      const h = document.createElement('span');
      h.className = 'tx-cut';
      h.tabIndex = 0;
      h.setAttribute('role', 'separator');
      h.setAttribute('aria-label', 'Start of this line: drag, or use the arrow keys, to move words between this line and the one above');
      h.title = 'Drag right: these words go to the line above. Drag onto the line above: its words come here. (← →)';
      r.querySelector('.tx-words').prepend(h);
    });
    if (dragging) dragging.querySelector('.tx-cut')?.classList.add('drag');
  };
  let dragging = null;  // the line whose start bar is being dragged (the bar itself is rebuilt as words move)
  const above = r => rows()[rows().indexOf(r) - 1];
  // move the boundary between line `up` and the next line so that `w` becomes the next line's first word
  const cutAt = (up, w) => {
    const down = rows()[rows().indexOf(up) + 1], all = [...words(up), ...words(down)], k = all.indexOf(w);
    if (k < 1 || k > all.length - 1 || words(down)[0] === w) return;  // each line keeps at least one word
    const pu = up.querySelector('.tx-words'), pd = down.querySelector('.tx-words');
    all.slice(0, k).forEach(x => pu.append(x, ' '));
    all.slice(k).reverse().forEach(x => pd.prepend(x, ' '));
    changed();
  };

  tx.addEventListener('pointerdown', e => {
    const h = e.target.closest('.tx-cut');
    if (!h) return;
    e.preventDefault();
    dragging = h.closest('.tx-row');
    h.classList.add('drag');
    tx.classList.add('dragging');
    const move = ev => {
      const up = above(dragging);
      const w = document.elementsFromPoint(ev.clientX, ev.clientY).find(x => x.classList && x.classList.contains('w'));
      if (w && up && (up.contains(w) || dragging.contains(w))) cutAt(up, w);
    };
    const end = () => {
      tx.querySelectorAll('.tx-cut.drag').forEach(x => x.classList.remove('drag'));
      tx.classList.remove('dragging');
      dragging = null;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', end);
    };
    document.addEventListener('pointermove', move);  // on the page, not the bar: the bar is rebuilt while dragging
    document.addEventListener('pointerup', end);
  });
  tx.addEventListener('keydown', e => {
    const h = e.target.closest('.tx-cut');
    if (!h || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    e.preventDefault();
    const down = h.closest('.tx-row'), up = above(down);
    // right: this line's first word goes up; left: the line above's last word comes down
    if (e.key === 'ArrowRight') cutAt(up, words(down)[1] || null);
    else cutAt(up, words(up).at(-1));
    down.querySelector('.tx-cut')?.focus();  // the bars were rebuilt: keep the focus on this line's bar
  });

  // a word: play from it, or start a new line there (the new line keeps the speaker until another is picked)
  tx.addEventListener('click', e => {
    const w = e.target.closest('.w');
    if (!w || !root.classList.contains('editing')) return;
    e.stopPropagation();
    if (menu) menu.remove();
    const row = w.closest('.tx-row'), first = words(row)[0] === w;
    menu = document.createElement('span');
    menu.className = 'tx-menu';
    menu.innerHTML = (video ? '<button type="button" data-a="play">Play from here</button>' : '') +
      (first ? '' : '<button type="button" data-a="split">New line from here</button>');
    if (!menu.innerHTML) { menu = null; return; }
    w.after(menu);
    menu.addEventListener('click', ev => {
      ev.stopPropagation();
      const b = ev.target.closest('button');
      const a = b && b.dataset.a;
      if (a === 'play') { video.currentTime = +w.dataset.s; video.play(); }
      if (a === 'split') {
        const n = row.cloneNode(true);
        n.classList.remove('on');
        const f = n.querySelector('.tx-flag');
        if (f) f.remove();
        const pn = n.querySelector('.tx-words'), rest = words(row).slice(words(row).indexOf(w));
        pn.textContent = '';
        rest.forEach(x => pn.append(x, ' '));
        row.after(n);
        n.querySelector('.tx-name select').value = row.dataset.spk;
        changed();
      }
      menu.remove();
      menu = null;
    });
  });
  document.addEventListener('click', e => {
    if (menu && !menu.contains(e.target) && !e.target.closest('.w')) { menu.remove(); menu = null; }
  });

  // a line's speaker: in edit mode the name is a list of the speakers (+ a new one)
  tx.addEventListener('change', e => {
    const sel = e.target.closest('.tx-name select');
    if (!sel) return;
    setSpeaker(sel.closest('.tx-row'), sel.value);
    changed();
  });
  if (editBtn) editBtn.addEventListener('click', () => {
    root.classList.add('editing');
    editBtn.hidden = true;
    help.hidden = false;
    rows().forEach(r => {
      const sel = document.createElement('select');
      sel.setAttribute('aria-label', 'Speaker of this line');
      sel.innerHTML = info.speakers.map((id, k) => `<option value="${id}">${info.names[k]}</option>`).join('') +
        '<option value="new">New speaker</option>';
      sel.value = r.dataset.spk;
      const tn = r.querySelector('.tx-name');
      tn.textContent = '';
      tn.append(sel);
      r.removeAttribute('role');
      r.removeAttribute('tabindex');
      r.removeAttribute('title');
    });
    refresh();
  });

  const save = async () => {
    const sentences = rows().map(r => ({ speaker: r.dataset.spk, words: words(r).map(w => +w.dataset.i) }));
    const btn = bar.querySelector('[data-edit-save]');
    btn.disabled = true;
    const res = await fetch(info.save, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sentences }) });
    if (res.ok) { bar.hidden = true; location.reload(); return; }
    btn.disabled = false;
    const err = await res.json().catch(() => ({}));
    alert('Could not save: ' + (err.detail || res.status));
  };
  if (bar) {
    bar.querySelector('[data-edit-save]').addEventListener('click', save);
    bar.querySelector('[data-edit-cancel]').addEventListener('click', () => { bar.hidden = true; location.reload(); });
  }
  window.addEventListener('beforeunload', e => { if (bar && !bar.hidden) e.preventDefault(); });

  // "Same as ...? Merge": every line of one speaker goes to the other, saved at once
  root.querySelectorAll('[data-merge]').forEach(b => b.addEventListener('click', () => {
    if (!confirm(`Merge ${name(b.dataset.merge)} into ${name(b.dataset.into)}? All their lines go to ${name(b.dataset.into)}.`)) return;
    rows().filter(r => r.dataset.spk === b.dataset.merge).forEach(r => setSpeaker(r, b.dataset.into));
    save();
  }));
});

// Live Dubbing (beta, dubbe/live.py): the stream's picture plays muted from its start, about DELAY seconds behind the
// stream; each dub piece (pieces.json: start t, length d, file f) plays on the picture's clock, so the two stay together.
// The picture waits when the dub has not reached it yet.
document.querySelectorAll('[data-live]').forEach(root => {
  const base = root.dataset.base, v = root.querySelector('[data-live-video]'), btn = root.querySelector('[data-live-play]');
  const info = root.querySelector('[data-live-info]'), lines = root.querySelector('[data-live-lines]');
  const pieces = [], loading = new Set();
  let ctx = null, state = 'starting', delay = 30, until = 0, hls = null, waiting = false, error = '';
  const decoder = new OfflineAudioContext(2, 1, 32000);  // decodes the pieces before Play (an AudioBuffer plays in any context)
  const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const stopAll = () => pieces.forEach(p => { if (p.src) { try { p.src.stop(); } catch (e) {} p.src = null; } });

  function attach() {  // the picture: hls.js (Chrome, Firefox) or the browser's own HLS (Safari)
    if (hls || v.src) return;
    if (window.Hls && Hls.isSupported()) {
      hls = new Hls({ startPosition: 0, liveDurationInfinity: false });
      hls.loadSource(base + 'video.m3u8');
      hls.attachMedia(v);
    } else v.src = base + 'video.m3u8';
  }

  async function poll() {
    try {
      const m = await (await fetch(base + 'pieces.json', { cache: 'no-store' })).json();
      state = m.state; delay = m.delay || delay; error = m.error || '';
      if (m.pieces.length) attach();
      for (const p of m.pieces) {
        if (loading.has(p.f)) continue;
        loading.add(p.f);
        const buf = await (await fetch(base + p.f)).arrayBuffer();
        const audio = await decoder.decodeAudioData(buf);
        pieces.push({ t: p.t, d: p.d, audio, lines: p.lines, src: null, at: 0 });
        until = Math.max(until, p.t + p.d);
      }
    } catch (e) { /* the list is being rewritten: next time */ }
    show();
    if (state === 'starting' || state === 'live') setTimeout(poll, 2000);
  }

  function show() {
    const ready = state === 'ended' || state === 'failed' ? until > 0 : until >= delay;
    btn.disabled = !ready;
    info.textContent = state === 'failed' ? 'The live dub stopped: ' + error
      : state === 'starting' ? 'Loading the models and opening the stream (about 30 s)…'
      : waiting ? `Waiting for the dub (ready up to ${clock(until)})…`
      : state === 'ended' ? `Ended · ${clock(until)} dubbed` + (ctx ? '' : ' · play it from the start')
      : ctx ? `Playing ${clock(v.currentTime)} · the dub is ready up to ${clock(until)}`
      : until >= delay ? 'Ready: press Play' : `Building up the delay: ${Math.round(until)} of ${delay} s dubbed`;
  }

  // every 250 ms: play the pieces at the picture's time; re-sync if they drift; wait when the dub is behind
  function tick() {
    if (!ctx) return;
    const now = v.currentTime, open = state === 'starting' || state === 'live';
    if (!v.paused && open && now > until - 1) { v.pause(); waiting = true; stopAll(); }
    else if (waiting && (until > now + 5 || !open)) { waiting = false; v.play(); }
    if (!v.paused && !v.seeking) {
      for (const p of pieces) {
        if (p.src) {  // drift: the audio clock against the picture's
          const expect = p.at + (now - p.t);
          if (Math.abs(ctx.currentTime - expect) > .15 && now < p.t + p.d) { p.src.stop(); p.src = null; }
          else continue;
        }
        if (p.t + p.d <= now || p.t > now + 1) continue;
        const s = ctx.createBufferSource();
        s.buffer = p.audio;
        s.connect(ctx.destination);
        const off = now - p.t;
        s.start(ctx.currentTime + Math.max(0, -off), Math.max(0, off));
        p.src = s; p.at = ctx.currentTime - off;
        s.onended = () => { if (p.src === s) p.src = null; };
      }
    }
    const said = pieces.flatMap(p => p.lines).filter(l => l.t <= now).slice(-4);
    lines.innerHTML = '';
    for (const l of said) {
      const row = document.createElement('p');
      row.innerHTML = `<span class="muted small"></span> <b></b><br><span class="muted"></span>`;
      row.children[0].textContent = clock(l.t); row.children[1].textContent = l.tgt; row.children[3].textContent = l.src;
      lines.append(row);
    }
    show();
  }

  btn.addEventListener('click', async () => {
    ctx = ctx || new AudioContext();
    await ctx.resume();
    attach();
    v.currentTime = 0;
    await v.play().catch(() => {});
    btn.hidden = true;
    setInterval(tick, 250);
  });
  ['pause', 'seeking', 'waiting'].forEach(e => v.addEventListener(e, stopAll));
  v.controls = true;
  poll();
});

// Side art (public pages, wide screens only): the original voice flows in down the left margin, Dubbe's dub flows out
// down the right - the same speech, cleaner on the way out. Still under prefers-reduced-motion; paused in hidden tabs.
document.querySelectorAll('canvas[data-wave]').forEach(c => {
  const ctx = c.getContext('2d'), out = c.dataset.wave === 'out';
  const cols = out ? ['#e5484d', '#6e56cf'] : ['#f76b15', '#e5484d'];
  let w = 0, h = 0, t = 0;
  const size = () => {
    const r = devicePixelRatio || 1;
    w = c.clientWidth; h = c.clientHeight; c.width = w * r; c.height = h * r; ctx.setTransform(r, 0, 0, r, 0, 0);
  };
  const level = s => {  // speech: syllables inside phrases, with fine detail in the original
    const syl = Math.max(0, Math.sin(s * 0.11)) ** 0.7, phrase = 0.3 + 0.7 * Math.max(0, Math.sin(s * 0.019 + 1));
    return syl * phrase * (out ? 1 : 0.7 + 0.3 * Math.sin(s * 1.3) * Math.sin(s * 0.47));
  };
  const draw = () => {
    ctx.clearRect(0, 0, w, h);
    if (w < 60) return;
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, cols[0]); g.addColorStop(1, cols[1]);
    ctx.fillStyle = g;
    const max = Math.min(w * 0.62, 180);
    for (let y = 48; y < h - 8; y += 7) {
      let v = level((y - t) / 1.6 + (out ? 40 : 0));
      if (out) v = Math.round(v * 6) / 6;  // processed: the same speech, in clean steps
      const bw = Math.max(2, v * max);
      ctx.globalAlpha = 0.42 * Math.min(1, (y - 40) / 160, (h - y) / 160);
      ctx.beginPath(); ctx.roundRect((w - bw) / 2, y, bw, 3, 1.5); ctx.fill();
    }
    ctx.globalAlpha = 1; ctx.fillStyle = '#a59f97'; ctx.font = '500 10px "Geist Mono", ui-monospace, monospace';
    ctx.textAlign = 'center'; ctx.fillText(out ? 'DUBBED VOICE' : 'ORIGINAL VOICE', w / 2, 26);
  };
  const tick = () => { if (!document.hidden && c.clientWidth) { t += 0.7; draw(); } requestAnimationFrame(tick); };
  addEventListener('resize', () => { size(); draw(); });
  size(); draw();
  if (!matchMedia('(prefers-reduced-motion: reduce)').matches) requestAnimationFrame(tick);
});

