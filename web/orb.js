/* Son of Anton orb: a small vanilla-canvas driver for the thinking-orbs engine (MIT, (c) 2026 Jakub Antalik).
   Orb(canvas,{size,preset,dots,dotSize,state}) -> {set(state),resize(px)}.
   States: working searching solving listening connecting weaving composing breathing shaping. State changes cross-fade. */
(function () {
  const E = window.OrbEngine;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  };
  const all = new Set(), FADE = 450;
  function Orb(canvas, o) {
    o = o || {};
    let size = o.size || 64, cur = null, prev = null, state = null, t0 = 0;
    const preset = o.preset || 64, dots = o.dots || 1, dsz = o.dotSize || 1, dpr = Math.min(2, window.devicePixelRatio || 1);
    const ctx = canvas.getContext('2d');
    const build = s => {
      const r = E.resolvePreset(s, preset);
      let op = r.opts;
      if (dots !== 1) op = E.scaleCounts(op, dots);
      if (dsz !== 1) op = E.scaleRadii(op, dsz);
      return { fn: E.MODE_FRAMES[r.mode], opts: op, speed: r.speed };
    };
    const fit = () => { canvas.width = canvas.height = Math.round(size * dpr); canvas.style.width = canvas.style.height = size + 'px'; };
    fit();
    const self = {
      set(s) {
        if (s === state) return;
        state = s; prev = cur; cur = build(s); t0 = performance.now();
        if (reduced) self.draw(0.6);
      },
      resize(n) {
        n = Math.round(n);
        if (n === size) return;
        size = n; fit();
        if (reduced) self.draw(0.6);
      },
      draw(sec) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, size, size);
        const dk = isDark(), p = prev ? Math.min(1, (performance.now() - t0) / FADE) : 1;
        if (prev && p < 1) {
          ctx.globalAlpha = 1 - p;
          E.paintFrame(ctx, prev.fn(size, sec * prev.speed, prev.opts), dk);
          ctx.globalAlpha = p;
        } else { prev = null; ctx.globalAlpha = 1; }
        E.paintFrame(ctx, cur.fn(size, sec * cur.speed, cur.opts), dk);
        ctx.globalAlpha = 1;
      },
      visible() { return canvas.offsetParent !== null; }
    };
    self.set(o.state || 'breathing');
    all.add(self);
    return self;
  }
  if (!reduced) {
    (function loop() {
      if (!document.hidden) {
        const t = performance.now() / 1000;
        all.forEach(o => { if (o.visible()) o.draw(t); });
      }
      requestAnimationFrame(loop);
    })();
  }
  window.Orb = Orb;
})();
