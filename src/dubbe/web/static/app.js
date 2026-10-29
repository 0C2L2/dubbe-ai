// DUBBE pages work without JavaScript; this only makes three things smoother.

// 1. Review editor: a click on a timeline block (report.timeline_html writes the number into #seg_pick input)
//    opens that sentence below the video.
const pick = document.querySelector('#seg_pick input');
if (pick) pick.addEventListener('input', () => {
  const d = document.getElementById('s' + pick.value);
  if (d) { d.open = true; d.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
});

// 2. Review editor: save text, tags and ratings without reloading, so the video keeps its place.
document.querySelectorAll('form.ajax').forEach(f => f.addEventListener('submit', async e => {
  e.preventDefault();
  const out = f.querySelector('.saved');
  const r = await fetch(f.action, {method: 'POST', body: new FormData(f), headers: {'X-Fetch': '1'}});
  out.textContent = r.ok ? 'Saved ✓' + (f.dataset.hint || '') : 'Not saved (error ' + r.status + ')';
}));

// 3. Upload areas: show the chosen file, highlight while dragging, and the file's length vs. the minutes left.
document.querySelectorAll('[data-drop]').forEach(zone => {
  const input = zone.querySelector('input[type=file]'), title = zone.querySelector('[data-drop-title]');
  const info = zone.querySelector('[data-drop-info]'), dur = document.getElementById('dur');
  const first = [title.textContent, info.textContent];
  ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, () => zone.classList.add('over')));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, () => zone.classList.remove('over')));
  input.addEventListener('change', () => {
    const f = input.files[0];
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
    [...voice.options].forEach(o => { o.hidden = o.dataset.lang !== lang.value && o.dataset.lang !== 'any'; });  // clones speak both
    if (voice.selectedOptions[0]?.hidden) voice.value = [...voice.options].find(o => !o.hidden)?.value;
    const s = voice.selectedOptions[0]?.dataset.sample;
    hear.hidden = !s; if (s) hear.dataset.play = s;
  };
  lang.addEventListener('change', sync); voice.addEventListener('change', sync); sync();
});

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
    [...sel.options].forEach(o => { if (o.dataset.lang) o.hidden = o.disabled = o.dataset.lang !== tgt.value && o.dataset.lang !== 'any'; });
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
