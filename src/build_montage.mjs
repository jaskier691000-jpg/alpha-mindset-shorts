// Writes the HyperFrames project of one video from its plan.json (made by make_video.py).
//   node src/build_montage.mjs <project dir>
// plan.json: { total, highlight, scenes: [{id, src, start, dur, media_start, zoom}], words: [{text, start, end}],
//              cards: [{text, start, end}], audio }
// Look validated by the owner on 31 Oct 2026: full-screen cinema clips with a slow push, dip-to-black cuts, white
// uppercase captions (≤ 3 words) whose spoken word turns gold, big punch cards at the top with a white flash.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const dir = process.argv[2];
const plan = JSON.parse(readFileSync(join(dir, "plan.json"), "utf8"));
const TOTAL = plan.total;
const HI = plan.highlight || "#f5c518";
const r = (x) => Math.round(x * 1000) / 1000;

// ---------- captions: ≤ 3 words per group, break on pauses; one gold word at a time ----------
const words = plan.words.map((w, i) => ({ ...w, id: `w${i}` }));
const groups = [];
let cur = [];
for (const [i, w] of words.entries()) {
  cur.push(w);
  const next = words[i + 1];
  if (cur.length === 3 || !next || next.start - w.end >= 0.15) {
    groups.push(cur);
    cur = [];
  }
}
groups.forEach((g, gi) => {
  g.start = r(Math.max(0.05, g[0].start - 0.06));
  const nextStart = groups[gi + 1] ? groups[gi + 1][0].start - 0.06 : TOTAL;
  g.end = r(Math.min(nextStart, g.at(-1).end + 0.4));
});
const capMarkup = groups
  .map((g, gi) => `    <div id="cg-${gi}" class="clip group" data-start="${g.start}" data-duration="${r(g.end - g.start)}"><div class="line">${g.map((w) => `<span id="cw-${w.id}" class="w">${w.text}</span>`).join(" ")}</div></div>`)
  .join("\n");
const capScript = groups
  .map((g, gi) => {
    const L = [`  tl.fromTo("#cg-${gi} .line", { y: 26, scale: 0.9, opacity: 0 }, { y: 0, scale: 1, opacity: 1, duration: 0.14, ease: "back.out(2.2)" }, ${g.start});`];
    g.forEach((w, wi) => {
      const on = r(Math.max(g.start, w.start));
      // back to white before the next word lights up, so two words are never gold together
      const nextOn = wi + 1 < g.length ? Math.max(g.start, g[wi + 1].start) : Infinity;
      const off = r(Math.max(on + 0.06, Math.min(g.end - 0.14, w.end + 0.04, nextOn - 0.01)));
      L.push(`  tl.fromTo("#cw-${w.id}", { color: "#ffffff" }, { color: "${HI}", duration: 0.05 }, ${on});`);
      L.push(`  tl.to("#cw-${w.id}", { color: "#ffffff", duration: 0.05 }, ${off});`);
    });
    L.push(`  tl.to("#cg-${gi} .line", { opacity: 0, duration: 0.1, ease: "power2.in" }, ${r(g.end - 0.1)});`);
    L.push(`  tl.set("#cg-${gi} .line", { opacity: 0, visibility: "hidden" }, ${g.end});`);
    return L.join("\n");
  })
  .join("\n");
const captions = `<template>
  <style>
    #root { position: absolute; inset: 0; }
    .group { position: absolute; left: 0; width: 100%; top: 1120px; text-align: center; overflow: visible; }
    .line { display: inline-block; max-width: 820px; font-family: "Montserrat", sans-serif; font-weight: 900; font-size: 86px;
      line-height: 1.05; text-transform: uppercase; color: #ffffff; text-shadow: 0 4px 0 rgba(0,0,0,0.6), 0 0 30px rgba(0,0,0,0.9); }
    .w { display: inline-block; }
  </style>
  <div id="root" data-composition-id="captions" data-width="1080" data-height="1920">
${capMarkup}
  </div>
  <script>
  const tl = gsap.timeline({ paused: true });
${capScript}
  window.__timelines["captions"] = tl;
  </script>
</template>
`;

// ---------- punch cards: the first (the hook) is on screen from frame 0 ----------
const cards = plan.cards.map((c, i) => ({ ...c, id: `card-${i}` }));
const cardMarkup = cards.map((c) => `    <div id="${c.id}" class="clip card" data-start="${c.start}" data-duration="${r(c.end - c.start)}"><div class="inner"><div class="big">${c.text}</div><div class="bar"></div></div></div>`).join("\n");
const cardScript = cards
  .map((c, i) =>
    [
      i === 0 && c.start === 0
        ? `  tl.fromTo("#${c.id} .big", { scale: 1, opacity: 1 }, { scale: 1, opacity: 1, duration: 0.01 }, 0);`
        : `  tl.fromTo("#${c.id} .big", { scale: 1.7, opacity: 0, filter: "blur(12px)" }, { scale: 1, opacity: 1, filter: "blur(0px)", duration: 0.28, ease: "power4.out" }, ${c.start});`,
      `  tl.fromTo("#${c.id} .bar", { scaleX: 0 }, { scaleX: 1, duration: 0.4, ease: "power3.out" }, ${r(c.start + 0.1)});`,
      `  tl.fromTo("#${c.id} .inner", { scale: 1 }, { scale: 1.07, duration: ${r(Math.max(0.3, c.end - c.start - 0.25))}, ease: "none" }, ${c.start});`,
      `  tl.to("#${c.id} .inner", { opacity: 0, y: -24, duration: 0.18, ease: "power2.in" }, ${r(c.end - 0.2)});`,
    ].join("\n"),
  )
  .join("\n");
const cardsHtml = `<template>
  <style>
    #root { position: absolute; inset: 0; }
    .card { position: absolute; left: 0; width: 100%; top: 330px; text-align: center; overflow: visible; }
    .inner { display: inline-block; max-width: 900px; }
    .big { font-family: "Archivo Black", sans-serif; font-size: 132px; line-height: 0.98; color: #ffffff; text-transform: uppercase;
      text-shadow: 0 0 44px rgba(245,197,24,0.55), 0 6px 0 rgba(0,0,0,0.55); }
    .bar { margin: 22px auto 0; width: 220px; height: 12px; background: ${HI}; transform-origin: center; }
  </style>
  <div id="root" data-composition-id="cards" data-width="1080" data-height="1920">
${cardMarkup}
  </div>
  <script>
  const tl = gsap.timeline({ paused: true });
${cardScript}
  window.__timelines["cards"] = tl;
  </script>
</template>
`;

// ---------- backgrounds: one clip per scene with a slow push, dip to black between scenes ----------
const bgTags = plan.scenes
  .map((s, i) => `      <video id="bg-${i}" class="clip bg" src="${s.src}" data-start="${s.start}" data-duration="${s.dur}"${s.media_start ? ` data-media-start="${s.media_start}"` : ""} data-track-index="0" muted playsinline style="z-index:${i + 1}"></video>`)
  .join("\n");
const bgScript = plan.scenes
  .map((s, i) => `      tl.fromTo("#bg-${i}", { scale: 1.0 }, { scale: ${s.zoom || 1.08}, duration: ${s.dur}, ease: "none" }, ${s.start});`)
  .join("\n");
const dipScript = plan.scenes
  .slice(1)
  .map((s, i) => `      tl.fromTo("#dip .black", { opacity: 0 }, { opacity: 0.85, duration: 0.12, ease: "power2.in"${i ? ", immediateRender: false" : ""} }, ${r(s.start - 0.12)});\n      tl.to("#dip .black", { opacity: 0, duration: 0.22, ease: "power2.out" }, ${s.start});`)
  .join("\n");
// accents: a short white flash when a punch card lands (the bass hit is already in the audio mix)
const flashScript = cards
  .filter((c) => c.start > 0)
  .map((c, i) => `      tl.fromTo("#flash .fill", { opacity: 0 }, { opacity: 0.55, duration: 0.05${i ? ", immediateRender: false" : ""} }, ${c.start});\n      tl.to("#flash .fill", { opacity: 0, duration: 0.25, ease: "power2.out" }, ${r(c.start + 0.05)});`)
  .join("\n");

const index = `<!doctype html>
<html lang="en" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: #000; }
      #root { width: 100%; height: 100%; position: relative; }
      .bg { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; object-fit: cover; }
      #shade, #dip, #flash { position: absolute; inset: 0; pointer-events: none; }
      #shade { z-index: 49; } #dip { z-index: 50; } #flash { z-index: 51; }
      #shade .grad { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 34%, rgba(0,0,0,0) 50%, rgba(0,0,0,0.6) 76%, rgba(0,0,0,0.25) 100%); }
      #dip .black { position: absolute; inset: 0; background: #000; opacity: 0; }
      #flash .fill { position: absolute; inset: 0; background: #fff; opacity: 0; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="${TOTAL}" data-width="1080" data-height="1920">
${bgTags}
      <div id="shade" class="clip" data-start="0" data-duration="${TOTAL}" data-track-index="1"><div class="grad"></div></div>
      <div id="dip" class="clip" data-start="0" data-duration="${TOTAL}" data-track-index="1"><div class="black"></div></div>
      <div id="flash" class="clip" data-start="0" data-duration="${TOTAL}" data-track-index="1"><div class="fill"></div></div>
      <div id="cards" data-composition-id="cards" data-composition-src="compositions/cards.html" data-start="0" data-duration="${TOTAL}"
        data-track-index="2" data-track-kind="graphics" data-width="1080" data-height="1920" style="z-index:60"></div>
      <div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-start="0" data-duration="${TOTAL}"
        data-track-index="3" data-track-kind="captions" data-width="1080" data-height="1920" style="z-index:70"></div>
      <audio id="mix" class="clip" src="${plan.audio}" data-start="0" data-track-index="5" data-volume="1"></audio>
    </div>
    <script>
      const tl = gsap.timeline({ paused: true });
${bgScript}
${dipScript}
${flashScript}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
`;

mkdirSync(join(dir, "compositions"), { recursive: true });
writeFileSync(join(dir, "index.html"), index);
writeFileSync(join(dir, "compositions", "captions.html"), captions);
writeFileSync(join(dir, "compositions", "cards.html"), cardsHtml);
writeFileSync(join(dir, "hyperframes.json"), JSON.stringify({ paths: { blocks: "compositions", assets: "assets" }, media: { autoProxy: true } }, null, 2));
writeFileSync(join(dir, "package.json"), JSON.stringify({ name: "alpha-video", private: true, type: "module" }, null, 2));
console.log(`montage: ${plan.scenes.length} scenes, ${groups.length} caption groups, ${cards.length} cards`);
