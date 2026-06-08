/* =============================================================
   OpenAfterHours — Polar Bear Constellation background.

   A polar bear drawn as a constellation (stars + bone-lines) that
   walks across the hero background. A nod to "computed at the speed
   of polars" (polars' polar-bear mascot → "URSA POLARIS").

   Desktop lifecycle, looping forever (CYCLE seconds):
     1. STAND   — reared up on hind legs (right, clear zone)
     2. CROUCH  — drops to all fours
     3. RUN     — gallops left→right, exits the right edge
     4. WALK-IN — re-enters from the left, crosses back
     5. RISE    — stands again

   On small screens (<= HIDE_BELOW px) the loop would put the centred
   bear behind the full-width hero text, so instead a one-shot intro
   plays: the bear stands centred, then bolts off the right edge while
   the hero copy is towed in from the left (a CSS animation on
   .hero-body, see homepage.css), after which the bear hides and only
   the starfield remains.

   Vanilla-JS port of the React/rAF prototype. Self-contained: it
   hydrates the first `.constellation-bg` element on the page and
   no-ops everywhere that element is absent (so it is safe to load
   site-wide). Respects prefers-reduced-motion by rendering a single
   static standing pose (or, on small screens, none). No dependencies;
   uses the shared --oah-* tokens via the .bear-svg / .bear-label CSS
   classes.
   ============================================================= */

(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  // Joint poses, normalised so the hip sits at (0,0). Bear faces +x (right).
  // Torso is a closed loop (spine + underside) so it reads as a bear, not a stick.
  var STAND = {
    hip: [0, 0], midBack: [1.5, -7], withers: [3, -13], neck: [4, -17],
    head: [6, -21], snout: [9, -21], ear: [5, -24],
    chest: [6, -12], belly: [4, -5],
    frontShoulder: [6, -13], frontKnee: [10, -12], frontPaw: [13, -11],
    backKnee: [-1, 8], backPaw: [-2, 15], tail: [-3, 3],
  };
  var QUAD = {
    hip: [0, 0], midBack: [7, -1.5], withers: [15, -2.5], neck: [19, -3],
    head: [22, -5], snout: [26, -4], ear: [21, -7.5],
    chest: [16, 3], belly: [8, 4.5],
    frontShoulder: [16, 1], frontKnee: [16.5, 7], frontPaw: [17, 13.5],
    backKnee: [-0.5, 6.5], backPaw: [-1, 13.5], tail: [-3, -1.5],
  };
  var BONES = [
    // spine (back)
    ["hip", "midBack"], ["midBack", "withers"], ["withers", "neck"],
    // underside (belly)
    ["hip", "belly"], ["belly", "chest"], ["chest", "neck"],
    // head
    ["neck", "head"], ["head", "snout"], ["head", "ear"],
    // front leg
    ["withers", "frontShoulder"], ["frontShoulder", "frontKnee"], ["frontKnee", "frontPaw"],
    // back leg
    ["hip", "backKnee"], ["backKnee", "backPaw"],
    // tail
    ["hip", "tail"],
  ];
  var NAMES = Object.keys(STAND);
  var STAR_R = {
    head: 0.9, snout: 0.82, hip: 0.88, withers: 0.74, ear: 0.58,
    backPaw: 0.55, frontPaw: 0.55,
  };

  // viewBox is 160×90 (16:9) with slice — bear never distorts.
  var VB_W = 160, VB_H = 90;
  var SCALE = 1.2;
  var CYCLE = 13.5;                 // seconds per full loop
  // Two rest anchors: the bear STANDS at the clear right spot, but its
  // on-all-fours rest stops earlier (the quad pose reaches ~31u forward vs
  // ~11u standing) so the head never clips the right edge before it rears up.
  var CX_STAND = 128, CX_QUAD = 114, CX_OFFR = 210, CX_OFFL = -48;
  var CY_STAND = 50, CY_RUN = 47;
  var STRIDE = 5, LIFT = 4.5;

  // Small-screen one-shot intro (see init/computeBear). At/below HIDE_BELOW the
  // bear stands centred then bolts off-right while the hero copy is towed in by a
  // CSS animation timed to INTRO_T0/INTRO_END. Keep in sync with homepage.css
  // .hero-body `bear-tow-in`: duration = INTRO_END - INTRO_T0 (5s), hold % =
  // (4 - INTRO_T0) / (INTRO_END - INTRO_T0) (50%).
  var HIDE_BELOW = 880;     // px — at/below this width, play the intro not the loop
  var INTRO_T0 = 1.5;       // intro start on the lifecycle clock (trims the stand)
  var INTRO_END = 6.5;      // intro end — bear has bolted off the right edge

  // Mobile-intro pose geometry (viewBox units) — used by mobileAnchors to centre
  // the bear's VISUAL extent (not its hip) and shrink it to fit a narrow band.
  var QUAD_SPAN = 29;       // all-fours x-extent: tail (-3) .. snout (26)
  var QUAD_FILL = 0.82;     // fraction of the visible band the all-fours pose fills
  var STAND_MID = 5;        // visual x-midpoint of the standing pose (tail -3 .. frontPaw 13)
  var QUAD_MID = 11.5;      // visual x-midpoint of the all-fours pose
  var MIN_SCALE = 0.7;      // never shrink the bear below this on tiny screens
  var SHAKE_A = 6;          // px — peak ground-shake at each footfall (mobile intro only)

  function lerp(a, b, t) { return a + (b - a) * t; }
  function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // Returns { pts, cx, cy, labelO } for time t and gallop phase. `a` is the
  // anchors object { standX, quadX, offRX, offLX, scale }: desktop passes the
  // module constants (endless loop), the mobile intro passes centred anchors.
  function computeBear(t, phase, a) {
    var blend, cx, cy, labelO, k;
    if (t < 3) {                              // STAND (clear zone)
      blend = 0; cx = a.standX; cy = CY_STAND; labelO = 1;
    } else if (t < 4) {                       // CROUCH (drops to all fours)
      k = ease(t - 3);
      blend = k; cx = lerp(a.standX, a.quadX, k); cy = lerp(CY_STAND, CY_RUN, k); labelO = 1 - k;
    } else if (t < 6.5) {                     // RUN → exits right
      k = ease((t - 4) / 2.5);
      blend = 1; cx = lerp(a.quadX, a.offRX, k); cy = CY_RUN; labelO = 0;
    } else if (t < 12.5) {                    // WALK-IN ← full width, settles right
      k = ease((t - 6.5) / 6);
      blend = 1; cx = lerp(a.offLX, a.quadX, k); cy = CY_RUN; labelO = 0;
    } else {                                  // RISE (rear up + drift right to rest)
      k = ease((t - 12.5) / 1);
      blend = 1 - k; cx = lerp(a.quadX, a.standX, k); cy = lerp(CY_RUN, CY_STAND, k); labelO = k;
    }

    // Gallop leg offsets (only when in the quad pose → scaled by blend)
    var legOff = function (phi) {
      var th = 2 * Math.PI * phase + phi;
      return [STRIDE * Math.cos(th), -LIFT * Math.max(0, Math.sin(th))];
    };
    var fp = legOff(0), bp = legOff(Math.PI);
    var bob = -1.2 * Math.abs(Math.sin(2 * Math.PI * phase)) * blend;
    var off = {
      frontPaw: [fp[0] * blend, fp[1] * blend],
      frontKnee: [0.5 * fp[0] * blend, 0.5 * fp[1] * blend],
      backPaw: [bp[0] * blend, bp[1] * blend],
      backKnee: [0.5 * bp[0] * blend, 0.5 * bp[1] * blend],
    };

    var pts = {};
    for (var i = 0; i < NAMES.length; i++) {
      var n = NAMES[i];
      var bx = lerp(STAND[n][0], QUAD[n][0], blend);
      var by = lerp(STAND[n][1], QUAD[n][1], blend);
      var o = off[n] || [0, 0];
      pts[n] = [cx + (bx + o[0]) * a.scale, cy + bob + (by + o[1]) * a.scale];
    }
    return { pts: pts, cx: cx, cy: cy + bob, labelO: labelO };
  }

  // Distant twinkling starfield (generated once, deterministic).
  function buildStarfield() {
    var s = 12345;
    var rnd = function () { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    var stars = [];
    for (var i = 0; i < 80; i++) {
      stars.push({
        x: rnd() * VB_W, y: rnd() * VB_H,
        r: 0.16 + rnd() * 0.42, tw: 2.5 + rnd() * 4, dl: -rnd() * 6,
      });
    }
    return stars;
  }

  function el(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, attrs[key]);
      }
    }
    return node;
  }

  // Build the SVG once and return the element refs the rAF loop updates.
  function buildSvg(host) {
    var svg = el("svg", {
      "class": "bear-svg",
      viewBox: "0 0 " + VB_W + " " + VB_H,
      preserveAspectRatio: "xMidYMid slice",
    });

    // distant starfield (declarative SMIL twinkle — runs without JS once created)
    var stars = buildStarfield();
    for (var i = 0; i < stars.length; i++) {
      var st = stars[i];
      var star = el("circle", { cx: st.x, cy: st.y, r: st.r, fill: "#e2e4e8", opacity: "0.5" });
      var tw = el("animate", {
        attributeName: "opacity", values: "0.18;0.6;0.18",
        dur: st.tw + "s", begin: st.dl + "s", repeatCount: "indefinite",
      });
      star.appendChild(tw);
      svg.appendChild(star);
    }

    // bear group: bones first, then glow+core stars
    var g = el("g", { "class": "bear-bones" });

    var lines = [];
    for (var b = 0; b < BONES.length; b++) {
      var line = el("line", {
        stroke: "rgba(255,145,0,0.42)", "stroke-width": "0.26", "stroke-linecap": "round",
      });
      g.appendChild(line);
      lines.push(line);
    }

    var joints = {};
    for (var j = 0; j < NAMES.length; j++) {
      var name = NAMES[j];
      var big = STAR_R[name] || 0.62;
      var coreFill = (name === "head" || name === "snout" || name === "ear") ? "#ffc857" : "#fff3e0";
      var glow = el("circle", { r: big * 2.6, fill: "#ff9100", opacity: "0.16" });
      var core = el("circle", { r: big, fill: coreFill });
      g.appendChild(glow);
      g.appendChild(core);
      joints[name] = { glow: glow, core: core };
    }
    svg.appendChild(g);

    // constellation name — fades in only while standing
    var label = el("text", { "class": "bear-label", "text-anchor": "middle" });
    label.textContent = "URSA POLARIS";
    svg.appendChild(label);

    host.appendChild(svg);
    return { lines: lines, joints: joints, label: label, group: g };
  }

  // Push a computed pose onto the existing SVG elements (no DOM churn).
  function render(refs, bear) {
    for (var b = 0; b < BONES.length; b++) {
      var a = bear.pts[BONES[b][0]];
      var c = bear.pts[BONES[b][1]];
      var line = refs.lines[b];
      line.setAttribute("x1", a[0]);
      line.setAttribute("y1", a[1]);
      line.setAttribute("x2", c[0]);
      line.setAttribute("y2", c[1]);
    }
    for (var name in refs.joints) {
      if (Object.prototype.hasOwnProperty.call(refs.joints, name)) {
        var p = bear.pts[name];
        var jt = refs.joints[name];
        jt.glow.setAttribute("cx", p[0]); jt.glow.setAttribute("cy", p[1]);
        jt.core.setAttribute("cx", p[0]); jt.core.setAttribute("cy", p[1]);
      }
    }
    refs.label.setAttribute("x", bear.cx);
    refs.label.setAttribute("y", bear.cy - 33);
    refs.label.setAttribute("opacity", bear.labelO);
  }

  // Frame the mobile intro: measure the slice-visible band, scale the bear to fit
  // it, and centre each pose's VISUAL extent (not the hip — the bear reaches
  // forward, so hip-centring pushes the head off the right edge as it drops to all
  // fours). Used only by the small-screen one-shot intro.
  function mobileAnchors(host) {
    var rect = host.getBoundingClientRect();
    var W = rect.width, H = rect.height, xR = 101;        // sane phone default
    if (W > 0 && H > 0) {
      var cover = Math.max(W / VB_W, H / VB_H);            // slice = cover = max
      xR = VB_W / 2 + (W / cover) / 2;                     // visible right edge, vb units
    }
    var band = 2 * (xR - VB_W / 2);                        // visible width, centred on 80
    var s = clamp(band * QUAD_FILL / QUAD_SPAN, MIN_SCALE, SCALE);
    var standX = VB_W / 2 - STAND_MID * s;                 // centre the standing pose
    var quadX = VB_W / 2 - QUAD_MID * s;                   // centre the all-fours pose
    return { standX: standX, quadX: quadX, offRX: xR + 40, offLX: standX, scale: s };
  }

  function init() {
    var host = document.querySelector(".constellation-bg");
    if (!host) { return; }                 // no-op off the landing page
    if (host.querySelector(".bear-svg")) { return; } // guard against double-init

    var refs = buildSvg(host);
    var DESKTOP = { standX: CX_STAND, quadX: CX_QUAD, offRX: CX_OFFR, offLX: CX_OFFL, scale: SCALE };

    var mqReduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    var mqSmall = window.matchMedia ? window.matchMedia("(max-width: " + HIDE_BELOW + "px)") : null;
    var reduced = function () { return !!(mqReduced && mqReduced.matches); };
    var small = function () { return !!(mqSmall && mqSmall.matches); };

    var rafId = null, t0 = null, last = null, phase = 0;
    var stop = function () { if (rafId != null) { cancelAnimationFrame(rafId); rafId = null; } };
    var setBearHidden = function (hidden) {
      var d = hidden ? "none" : "";
      refs.group.style.display = d; refs.label.style.display = d;
    };

    // Ground shake: a footfall-synced camera shake on the whole hero (mobile intro).
    var heroEl = host.closest(".landing-hero") || host;
    var applyShake = function (s, foot) {
      if (s <= 0.001) { heroEl.style.transform = ""; return; }
      var dir = (Math.floor(foot) % 2 === 0) ? 1 : -1;        // alternate sway per footfall
      var dx = (SHAKE_A * 0.35 * s * dir).toFixed(2);
      var dy = (SHAKE_A * s).toFixed(2);
      heroEl.style.transform = "translate3d(" + dx + "px," + dy + "px,0)";
    };

    // Desktop: endless walk (today's behaviour, now via the anchors param).
    var loopTick = function (now) {
      if (t0 == null) { t0 = now; last = now; }
      var dt = Math.min(0.05, (now - last) / 1000); last = now;
      var t = ((now - t0) / 1000) % CYCLE;
      var freq = 0;
      if (t >= 3 && t < 4) { freq = 0.7; }
      else if (t >= 4 && t < 6.5) { freq = 1.9; }
      else if (t >= 6.5 && t < 12.5) { freq = 0.95; }
      else if (t >= 12.5) { freq = 0.5; }
      phase += freq * dt;
      render(refs, computeBear(t, phase, DESKTOP));
      rafId = requestAnimationFrame(loopTick);
    };
    var startLoop = function () {
      if (rafId == null) { t0 = null; last = null; rafId = requestAnimationFrame(loopTick); }
    };

    // Mobile: one-shot stand → bolt off right (hero text tows in via CSS, and the
    // hero shakes in time with the gallop footfalls).
    var introTick = function (now) {
      if (t0 == null) { t0 = now; last = now; }
      var dt = Math.min(0.05, (now - last) / 1000); last = now;
      var t = INTRO_T0 + (now - t0) / 1000;               // one-shot, not modulo
      var freq = (t >= 3 && t < 4) ? 0.7 : (t >= 4 ? 1.9 : 0);
      phase += freq * dt;
      var anchors = mobileAnchors(host);
      var bear = computeBear(t, phase, anchors);
      render(refs, bear);
      // ground shake: footfall-synced jolt, ramped by the gallop, faded as it exits
      var gallop = (t < 3) ? 0 : (t < 4 ? ease(t - 3) : 1);
      var xR = anchors.offRX - 40;                         // visible right edge (vb units)
      var presence = clamp((xR + 4 - bear.cx) / 24, 0, 1); // 1 on-screen → 0 once it leaves
      var foot = phase * 2;                                // 2 footfalls per stride cycle
      var u = foot - Math.floor(foot);
      applyShake((1 - u) * (1 - u) * gallop * presence, foot);
      if (t >= INTRO_END) { stop(); setBearHidden(true); heroEl.style.transform = ""; return; }
      rafId = requestAnimationFrame(introTick);
    };
    var startIntro = function () {
      stop(); setBearHidden(false); t0 = null; last = null; phase = 0;
      rafId = requestAnimationFrame(introTick);
    };

    // The mobile intro is driven by an IntersectionObserver so it plays the moment
    // the hero is actually on-screen (not lost in the initial paint) and replays
    // whenever the hero re-enters view.
    var io = null, inView = false, firstPlay = true;
    var retriggerTextTow = function () {        // restart the CSS .hero-body tow-in
      var hb = document.querySelector(".hero-body");
      if (!hb) { return; }
      hb.style.animation = "none";
      void hb.offsetWidth;                      // force reflow so it can restart
      hb.style.animation = "";                   // resume the stylesheet animation
    };
    var teardownObserver = function () {
      if (io) { io.disconnect(); io = null; }
      inView = false;
      heroEl.style.transform = "";               // drop any leftover ground-shake
    };
    var setupObserver = function () {
      if (io) { return; }                       // already observing
      if (!("IntersectionObserver" in window)) { startIntro(); return; } // old browser
      io = new IntersectionObserver(function (entries) {
        var vis = entries[entries.length - 1].isIntersecting;
        if (vis && !inView) {
          inView = true;
          startIntro();                          // bear: stand → bolt off (the bounce)
          if (!firstPlay) { retriggerTextTow(); } // first paint: CSS auto-plays the text;
          firstPlay = false;                      //   re-entries: JS re-tows it in sync
        } else if (!vis) {
          inView = false;                         // left view → arm replay on return
        }
      }, { threshold: 0.5 });
      io.observe(heroEl);
    };

    var update = function () {
      if (small()) {
        if (reduced()) { teardownObserver(); stop(); setBearHidden(true); return; }
        setBearHidden(true);                      // hide until the observer fires (no flash)
        setupObserver();                          // observer drives play + replay
        return;
      }
      teardownObserver();                          // desktop
      setBearHidden(false);
      if (reduced()) { stop(); render(refs, computeBear(0, 0, DESKTOP)); return; }
      startLoop();
    };

    update();
    var listen = function (mq) {
      if (!mq) { return; }
      if (mq.addEventListener) { mq.addEventListener("change", update); }
      else if (mq.addListener) { mq.addListener(update); }  // older Safari
    };
    listen(mqSmall); listen(mqReduced);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
