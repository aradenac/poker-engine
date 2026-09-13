// Installed only by the offline arena, after loading the production analyser.
// Production HTML and its strategy are never rewritten.
({trials}) => {
  const random = seed => () => {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  const hash = text => {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
    return h >>> 0;
  };
  const NativeBlob = window.Blob, NativeWorker = window.Worker;
  window.__arena = {seed: 0, observations: [], errors: []};
  window.__arenaReset = seed => {
    window.__arena.seed = seed;
    Math.random = random(seed);
  };
  window.Blob = class extends NativeBlob {
    constructor(parts, options) {
      if (options?.type === 'text/javascript' && parts.some(p => typeof p === 'string' && p.includes('self.onmessage'))) {
        const prefix = `self.addEventListener('message', e => {
          Math.random = (${random.toString()})(e.data.__arenaSeed);
        });\n`;
        parts = [prefix, ...parts];
      }
      super(parts, options);
    }
  };
  window.Worker = class extends NativeWorker {
    constructor(...args) {
      super(...args);
      this.addEventListener('message', e => {
        if (e.data?.type !== 'result') return;
        const out = e.data.out;
        const count = out?.trials ?? (out?.method === 'Monte-Carlo' ? out.scenarios : null);
        if (count !== null) {
          window.__arena.observations.push(count);
          if (count !== trials) window.__arena.errors.push(`Requested ${trials}, executed ${count}`);
        }
      });
    }
    postMessage(data, ...rest) {
      const seed = hash(String(window.__arena.seed) + ':' + JSON.stringify(data));
      super.postMessage({...data, trials, __arenaSeed: seed}, ...rest);
    }
  };
}
