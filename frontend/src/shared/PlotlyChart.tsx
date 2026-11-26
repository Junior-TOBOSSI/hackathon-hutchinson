import { useEffect, useRef } from "react";

/** Minimal Plotly wrapper. plotly.js-dist-min is loaded lazily (separate chunk). */
export function PlotlyChart({ data, layout }: { data: unknown[]; layout?: Record<string, unknown> }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = ref.current;
    let cancelled = false;
    let plotly: typeof import("plotly.js-dist-min").default | undefined;
    void import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (cancelled || !element) return;
      plotly = Plotly;
      void Plotly.react(
        element,
        data,
        {
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          font: { color: "#cbd5e1" },
          margin: { t: 20, r: 10, b: 40, l: 40 },
          ...layout,
        },
        { displayModeBar: false, responsive: true },
      );
    });
    return () => {
      cancelled = true;
      if (element && plotly) plotly.purge(element);
    };
  }, [data, layout]);

  return <div ref={ref} className="h-72 w-full" />;
}
