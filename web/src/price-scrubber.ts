import type { View } from "vega";
import { chartBars } from "./chart";
import type { Slot } from "./data";

// A touch-friendly slider over Vega's plot. It uses the same half-hour geometry
// as the bars, including missing prices and the repeated autumn clock hour.
export function attachPriceScrubber(
  chart: HTMLElement,
  view: View,
  slots: Slot[],
) {
  const byStart = new Map(slots.map((slot) => [slot.start, slot]));
  const bands = chartBars(
    slots.map((slot) => ({ ...slot, price: slot.price ?? 0 })),
  );
  const slider = document.createElement("div");
  slider.className = "price-scrubber";
  slider.tabIndex = 0;
  slider.setAttribute("role", "slider");
  slider.setAttribute(
    "aria-label",
    `${chart.getAttribute("aria-label")}. Explore half-hour prices`,
  );
  slider.setAttribute("aria-valuemin", "0");
  slider.setAttribute("aria-valuemax", String(bands.length - 1));
  slider.setAttribute("aria-valuenow", "0");
  slider.setAttribute(
    "aria-valuetext",
    "Touch or use arrow keys to explore prices",
  );
  const line = document.createElement("div");
  line.className = "scrubber-line";
  const label = document.createElement("div");
  label.className = "scrubber-price";
  label.setAttribute("aria-hidden", "true");
  line.hidden = label.hidden = true;
  slider.append(line, label);
  chart.append(slider);
  let selected: number | undefined;
  let gesture:
    { id: number; x: number; y: number; dragging: boolean } | undefined;
  let frame = 0;

  function display(index: number) {
    selected = Math.max(0, Math.min(bands.length - 1, index));
    const band = bands[selected];
    const slot = byStart.get(band.start)!;
    const price =
      slot.price === null ? "Unavailable" : `${slot.price.toFixed(1)}p/kWh`;
    const hour = Math.floor(slot.minute / 60);
    const minutes = slot.minute % 60;
    const time = `${hour % 12 || 12}${minutes ? `:${String(minutes).padStart(2, "0")}` : ""}${hour < 12 ? "am" : "pm"}`;
    label.textContent = `${time}: ${price}`;
    line.hidden = label.hidden = false;
    const x =
      ((band.band_start + band.band_end) / 2 / 1440) * slider.clientWidth;
    line.style.left = `${x}px`;
    // Keep the price readable at midnight and the last half-hour too.
    const half = label.offsetWidth / 2;
    label.style.left = `${Math.max(half, Math.min(slider.clientWidth - half, x))}px`;
    slider.setAttribute("aria-valuenow", String(selected));
    slider.setAttribute(
      "aria-valuetext",
      `${slot.clock}: ${price}${slot.status === "predicted" ? ", estimated" : ""}`,
    );
    slider.dataset.start = slot.start;
  }
  function selectAt(clientX: number) {
    const rect = slider.getBoundingClientRect();
    const minute = Math.max(
      0,
      Math.min(1439.999, ((clientX - rect.left) / rect.width) * 1440),
    );
    const index = bands.findIndex(
      (band) => minute >= band.band_start && minute < band.band_end,
    );
    if (index >= 0) display(index);
  }
  function position() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const plot = chart.querySelector<SVGGElement>("svg .role-frame > g");
      const matrix = plot?.getScreenCTM();
      if (!matrix) return;
      const bounds = chart.getBoundingClientRect();
      Object.assign(slider.style, {
        left: `${matrix.e - bounds.left}px`,
        top: `${matrix.f - bounds.top}px`,
        width: `${Number(view.signal("width")) * matrix.a}px`,
        height: `${Number(view.signal("height")) * matrix.d}px`,
      });
      if (selected !== undefined) display(selected);
    });
  }
  slider.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0) return;
    gesture = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      dragging: event.pointerType !== "touch",
    };
    slider.setPointerCapture(event.pointerId);
    if (gesture.dragging) selectAt(event.clientX);
  });
  slider.addEventListener("pointermove", (event) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = Math.abs(event.clientX - gesture.x);
    const dy = Math.abs(event.clientY - gesture.y);
    if (!gesture.dragging && dx > 6 && dx > dy) gesture.dragging = true;
    if (gesture.dragging) selectAt(event.clientX);
  });
  slider.addEventListener("pointerup", (event) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    if (
      gesture.dragging ||
      Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) < 8
    )
      selectAt(event.clientX);
    gesture = undefined;
  });
  slider.addEventListener("pointercancel", () => {
    gesture = undefined;
  });
  slider.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      selected = undefined;
      line.hidden = label.hidden = true;
      return;
    }
    const index = selected ?? 0;
    const next =
      event.key === "ArrowRight" || event.key === "ArrowUp"
        ? index + 1
        : event.key === "ArrowLeft" || event.key === "ArrowDown"
          ? index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? bands.length - 1
              : undefined;
    if (next !== undefined) {
      event.preventDefault();
      display(next);
    }
  });
  const observer = new ResizeObserver(position);
  observer.observe(chart);
  view.addSignalListener("width", position);
  position();
  return () => {
    cancelAnimationFrame(frame);
    observer.disconnect();
    view.removeSignalListener("width", position);
    slider.remove();
  };
}
