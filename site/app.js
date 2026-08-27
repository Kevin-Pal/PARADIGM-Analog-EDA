(() => {
  "use strict";

  // Every axis is oriented so that further from the origin means a better design.
  // Gain and GBW already work that way; power does not, so it is plotted as its
  // reciprocal -- the same quantity the paper's fitness function uses for power
  // (Eq. 3 takes C = 1/Pdiss). Tooltips still report the true dissipation in mW.
  const metrics = {
    g: { label: "DC gain", unit: "dB", short: "Gain" },
    b: { label: "Gain-bandwidth product", unit: "MHz", short: "GBW" },
    p: { label: "Power efficiency", unit: "1/mW", short: "Pdiss",
         plot: (v) => 1 / v },
  };

  // Value as it is positioned on an axis (may differ from the value shown in the tooltip).
  const plotted = (key, value) => (metrics[key].plot ? metrics[key].plot(value) : value);

  const topologyOrder = ["SMC", "NGCC", "DFCFC1", "TCFC", "IAC", "NMCNR", "AZC"];
  const colors = {
    SMC: "#007f74",
    NGCC: "#d47718",
    DFCFC1: "#7563c9",
    TCFC: "#d04a66",
    IAC: "#2d73b9",
    NMCNR: "#7a8b2e",
    AZC: "#9a5a33",
  };

  const canvas = document.querySelector("#pareto-chart");
  if (!canvas) return;

  const context = canvas.getContext("2d");
  const chartWrap = canvas.parentElement;
  const tooltip = document.querySelector("#chart-tooltip");
  const loading = document.querySelector("#chart-loading");
  const status = document.querySelector("#chart-status");
  const legend = document.querySelector("#chart-legend");
  const xMetric = document.querySelector("#x-metric");
  const yMetric = document.querySelector("#y-metric");
  const xScale = document.querySelector("#x-scale");
  const yScale = document.querySelector("#y-scale");
  const paretoOnly = document.querySelector("#pareto-only");

  let points = [];
  let projected = [];
  let activePoint = null;
  const visibleTopologies = new Set(topologyOrder);

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function compactNumber(value) {
    if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (value >= 100) return value.toFixed(0);
    if (value >= 10) return value.toFixed(1).replace(/\.0$/, "");
    if (value >= 1) return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
    if (value >= 0.01) return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    return value.toExponential(0).replace("e-", "×10⁻");
  }

  function fullNumber(value, digits = 4) {
    return value.toLocaleString(undefined, { maximumFractionDigits: digits });
  }

  function transform(value, scale) {
    return scale === "log" ? Math.log10(value) : value;
  }

  function niceLinearExtent(min, max) {
    const span = max - min || Math.abs(max) || 1;
    const pad = span * 0.06;
    return [min - pad, max + pad];
  }

  function logExtent(min, max) {
    const logMin = Math.log10(min);
    const logMax = Math.log10(max);
    const pad = (logMax - logMin || 1) * 0.035;
    return [logMin - pad, logMax + pad];
  }

  function linearTicks(min, max, count = 5) {
    const raw = (max - min) / Math.max(1, count);
    const power = 10 ** Math.floor(Math.log10(raw));
    const error = raw / power;
    const factor = error >= 5 ? 5 : error >= 2 ? 2 : 1;
    const step = factor * power;
    // Guard: a degenerate extent (min === max, or a non-finite bound) makes `step`
    // 0 or NaN, which would turn the loop below into an infinite one.
    if (!Number.isFinite(step) || step <= 0 || !Number.isFinite(min) || !Number.isFinite(max)) return [];
    const start = Math.ceil(min / step) * step;
    const ticks = [];
    for (let value = start; value <= max + step * 0.001 && ticks.length < 64; value += step) ticks.push(value);
    return ticks;
  }

  function logTicks(min, max) {
    const start = Math.ceil(min);
    const end = Math.floor(max);
    // Guard: ±Infinity bounds (e.g. log10 of a non-positive value) would make
    // `exponent += 1` a no-op and spin forever.
    if (!Number.isFinite(start) || !Number.isFinite(end)) return [];
    const ticks = [];
    const span = end - start;
    for (let exponent = start; exponent <= end && ticks.length < 64; exponent += 1) {
      ticks.push(exponent);
      if (span <= 3) {
        const two = Math.log10(2 * 10 ** exponent);
        const five = Math.log10(5 * 10 ** exponent);
        if (two < max) ticks.push(two);
        if (five < max) ticks.push(five);
      }
    }
    return ticks.sort((a, b) => a - b);
  }

  function setCanvasSize() {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(300, Math.round(rect.width));
    const height = Math.max(300, Math.round(rect.height));
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { width, height };
  }

  function filteredPoints() {
    return points.filter((point) => visibleTopologies.has(point.c) && (!paretoOnly.checked || point.o === 1));
  }

  // Axis captions carry the direction, because a reversed axis is otherwise easy to misread.
  function axisTitle(key, mode) {
    const m = metrics[key];
    return `${m.label} (${m.unit})${mode === "log" ? " · log" : ""}`;
  }

  function draw() {
    if (!points.length) return;
    const { width, height } = setCanvasSize();
    const mobile = width < 560;
    const margin = mobile
      ? { top: 24, right: 18, bottom: 57, left: 63 }
      : { top: 28, right: 28, bottom: 64, left: 82 };
    const plotWidth = Math.max(10, width - margin.left - margin.right);
    const plotHeight = Math.max(10, height - margin.top - margin.bottom);
    const selected = filteredPoints();
    const xKey = xMetric.value;
    const yKey = yMetric.value;
    const xMode = xScale.value;
    const yMode = yScale.value;
    const ink = css("--ink");
    const muted = css("--muted");
    const line = css("--line");
    const surface = css("--surface");

    context.clearRect(0, 0, width, height);
    context.fillStyle = surface;
    context.fillRect(0, 0, width, height);
    projected = [];

    if (!selected.length) {
      context.fillStyle = muted;
      context.font = `13px ${css("--font-sans")}`;
      context.textAlign = "center";
      context.fillText("No topologies are visible. Use the legend to restore a series.", width / 2, height / 2);
      status.textContent = "0 designs visible";
      return;
    }

    const xValues = selected.map((point) => plotted(xKey, point[xKey]));
    const yValues = selected.map((point) => plotted(yKey, point[yKey]));
    const xExtent = xMode === "log"
      ? logExtent(Math.min(...xValues), Math.max(...xValues))
      : niceLinearExtent(Math.min(...xValues), Math.max(...xValues));
    const yExtent = yMode === "log"
      ? logExtent(Math.min(...yValues), Math.max(...yValues))
      : niceLinearExtent(Math.min(...yValues), Math.max(...yValues));
    // px/py take a value already in plot space (see `plotted`).
    const px = (value) => margin.left + ((transform(value, xMode) - xExtent[0]) / (xExtent[1] - xExtent[0])) * plotWidth;
    const py = (value) => margin.top + plotHeight - ((transform(value, yMode) - yExtent[0]) / (yExtent[1] - yExtent[0])) * plotHeight;
    const xTicks = xMode === "log" ? logTicks(...xExtent) : linearTicks(...xExtent);
    const yTicks = yMode === "log" ? logTicks(...yExtent) : linearTicks(...yExtent);

    context.save();
    context.strokeStyle = line;
    context.lineWidth = 1;
    context.fillStyle = muted;
    context.font = `${mobile ? 10 : 11}px ${css("--font-mono")}`;
    context.textAlign = "center";
    context.textBaseline = "top";
    xTicks.forEach((tick) => {
      const value = xMode === "log" ? 10 ** tick : tick;
      const x = px(value);
      context.beginPath();
      context.moveTo(x, margin.top);
      context.lineTo(x, margin.top + plotHeight);
      context.stroke();
      context.fillText(compactNumber(value), x, margin.top + plotHeight + 9);
    });
    context.textAlign = "right";
    context.textBaseline = "middle";
    yTicks.forEach((tick) => {
      const value = yMode === "log" ? 10 ** tick : tick;
      const y = py(value);
      context.beginPath();
      context.moveTo(margin.left, y);
      context.lineTo(margin.left + plotWidth, y);
      context.stroke();
      context.fillText(compactNumber(value), margin.left - 10, y);
    });
    context.strokeStyle = ink;
    context.beginPath();
    context.moveTo(margin.left, margin.top);
    context.lineTo(margin.left, margin.top + plotHeight);
    context.lineTo(margin.left + plotWidth, margin.top + plotHeight);
    context.stroke();
    context.fillStyle = ink;
    context.font = `600 ${mobile ? 11 : 12}px ${css("--font-sans")}`;
    context.textAlign = "center";
    context.textBaseline = "bottom";
    context.fillText(`${axisTitle(xKey, xMode)} →`, margin.left + plotWidth / 2, height - 5);
    context.save();
    context.translate(15, margin.top + plotHeight / 2);
    context.rotate(-Math.PI / 2);
    context.fillText(`${axisTitle(yKey, yMode)} →`, 0, 0);
    context.restore();
    context.restore();

    const ordered = selected.slice().sort((a, b) => a.o - b.o);
    ordered.forEach((point) => {
      const x = px(plotted(xKey, point[xKey]));
      const y = py(plotted(yKey, point[yKey]));
      projected.push({ x, y, point });
      context.beginPath();
      context.arc(x, y, point.o === 1 ? (mobile ? 2.6 : 3.1) : 2.1, 0, Math.PI * 2);
      context.fillStyle = colors[point.c];
      context.globalAlpha = point.o === 1 ? 0.88 : 0.16;
      context.fill();
    });
    context.globalAlpha = 1;

    if (activePoint && selected.includes(activePoint)) {
      const target = projected.find((item) => item.point === activePoint);
      if (target) {
        context.beginPath();
        context.arc(target.x, target.y, 7, 0, Math.PI * 2);
        context.strokeStyle = ink;
        context.lineWidth = 1.5;
        context.stroke();
      }
    }

    const paretoCount = selected.reduce((sum, point) => sum + (point.o === 1 ? 1 : 0), 0);
    status.textContent = `${selected.length.toLocaleString()} designs visible · ${paretoCount.toLocaleString()} Pareto-optimal`;
  }

  function nearestPoint(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    let nearest = null;
    let minDistance = 15;
    for (const item of projected) {
      const distance = Math.hypot(item.x - x, item.y - y);
      if (distance < minDistance) {
        minDistance = distance;
        nearest = item;
      }
    }
    return nearest;
  }

  function showTooltip(item) {
    if (!item) {
      activePoint = null;
      tooltip.hidden = true;
      draw();
      return;
    }
    activePoint = item.point;
    tooltip.innerHTML = `<strong><i style="background:${colors[item.point.c]}"></i>${item.point.c} · ${item.point.o === 1 ? "Pareto-optimal" : "evaluated"}</strong><span>Gain&nbsp; ${fullNumber(item.point.g, 3)} dB<br>GBW&nbsp; ${fullNumber(item.point.b, 4)} MHz<br>Pdiss&nbsp; ${fullNumber(item.point.p, 4)} mW</span>`;
    tooltip.querySelector("i").style.cssText += ";display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px";
    tooltip.hidden = false;
    const wrapRect = chartWrap.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    let left = item.x + 14;
    let top = item.y - tooltipRect.height - 10;
    if (left + tooltipRect.width > wrapRect.width - 8) left = item.x - tooltipRect.width - 14;
    if (top < 8) top = item.y + 14;
    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
    draw();
  }

  function pointerTooltip(event) {
    showTooltip(nearestPoint(event.clientX, event.clientY));
  }

  function buildLegend() {
    topologyOrder.forEach((topology) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "legend-button";
      button.textContent = topology;
      button.style.setProperty("--series-color", colors[topology]);
      button.setAttribute("aria-pressed", "true");
      button.setAttribute("aria-label", `Hide ${topology}`);
      button.addEventListener("click", () => {
        const isVisible = visibleTopologies.has(topology);
        if (isVisible) visibleTopologies.delete(topology);
        else visibleTopologies.add(topology);
        button.setAttribute("aria-pressed", String(!isVisible));
        button.setAttribute("aria-label", `${isVisible ? "Show" : "Hide"} ${topology}`);
        activePoint = null;
        tooltip.hidden = true;
        draw();
      });
      legend.append(button);
    });
  }

  function avoidDuplicateAxes(changed) {
    if (xMetric.value !== yMetric.value) return;
    const fallback = Object.keys(metrics).find((key) => key !== changed.value);
    if (changed === xMetric) yMetric.value = fallback;
    else xMetric.value = fallback;
  }

  [xMetric, yMetric].forEach((control) => control.addEventListener("change", () => {
    avoidDuplicateAxes(control);
    activePoint = null;
    tooltip.hidden = true;
    draw();
  }));
  [xScale, yScale, paretoOnly].forEach((control) => control.addEventListener("change", () => {
    activePoint = null;
    tooltip.hidden = true;
    draw();
  }));
  canvas.addEventListener("pointermove", (event) => {
    if (event.pointerType === "mouse" || event.buttons) pointerTooltip(event);
  });
  canvas.addEventListener("pointerdown", pointerTooltip);
  canvas.addEventListener("pointerleave", () => {
    if (!matchMedia("(hover: none)").matches) showTooltip(null);
  });
  canvas.addEventListener("keydown", (event) => {
    const navigationKeys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "Escape"];
    if (!navigationKeys.includes(event.key)) return;
    event.preventDefault();

    if (event.key === "Escape") {
      showTooltip(null);
      return;
    }

    const candidates = projected.slice().sort((a, b) => a.x - b.x || a.y - b.y);
    if (!candidates.length) return;
    const activeIndex = candidates.findIndex((item) => item.point === activePoint);
    let nextIndex;
    if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = candidates.length - 1;
    else if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = activeIndex < 0 ? 0 : Math.min(activeIndex + 1, candidates.length - 1);
    else nextIndex = activeIndex < 0 ? candidates.length - 1 : Math.max(activeIndex - 1, 0);
    showTooltip(candidates[nextIndex]);
  });
  canvas.addEventListener("blur", () => showTooltip(null));

  buildLegend();

  fetch("data/pareto.json")
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (!data || !Array.isArray(data.points) || !data.points.length) throw new Error("Unexpected data format");
      points = data.points;
      loading.hidden = true;
      draw();
    })
    .catch(() => {
      loading.textContent = "The database could not be loaded. Serve the site over HTTP and try again.";
      status.textContent = "Database unavailable";
    });

  // Observe the wrapper, not the canvas. draw() writes canvas.width/height, which
  // changes the canvas's own layout size -- observing the canvas therefore feeds
  // straight back into draw() and spins forever (renderer freeze). The wrapper is
  // sized by CSS, so it is stable to observe. The re-entrancy flag provides a
  // second safeguard against feedback.
  let drawing = false;
  const safeDraw = () => {
    if (drawing) return;
    drawing = true;
    try { draw(); } finally { drawing = false; }
  };
  const resizeObserver = new ResizeObserver(() => safeDraw());
  resizeObserver.observe(chartWrap);
  const colorScheme = matchMedia("(prefers-color-scheme: dark)");
  colorScheme.addEventListener?.("change", draw);

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      const value = target.innerText;
      try {
        await navigator.clipboard.writeText(value);
      } catch {
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand("copy");
        selection.removeAllRanges();
      }
      const original = button.textContent;
      button.textContent = "Copied";
      button.setAttribute("aria-label", "Copied to clipboard");
      window.setTimeout(() => {
        button.textContent = original;
        button.removeAttribute("aria-label");
      }, 1600);
    });
  });
})();
