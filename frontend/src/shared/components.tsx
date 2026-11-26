import type { ReactNode } from "react";

import type { PartVerdict } from "../api/types";

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-argos-line bg-argos-panel p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-argos-cyan">{title}</h2>
      {children}
    </section>
  );
}

export function StatTile({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded border border-argos-line px-4 py-3">
      <div className="text-xs uppercase text-slate-400">{label}</div>
      <div className={`text-2xl font-semibold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

const VERDICT_TONE: Record<PartVerdict, string> = {
  OK: "bg-verdict-ok",
  NOK: "bg-verdict-nok",
  HOLD: "bg-verdict-hold text-black",
  ERROR: "bg-verdict-error",
};

export function VerdictBadge({ verdict }: { verdict: PartVerdict }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${VERDICT_TONE[verdict]}`}>{verdict}</span>;
}

export function SimulatedBadge() {
  return <span className="rounded bg-slate-600 px-1.5 py-0.5 text-[10px] uppercase">simulé</span>;
}

export function QueryState({ isLoading, error }: { isLoading: boolean; error: unknown }) {
  if (isLoading) return <p className="text-sm text-slate-400">Chargement…</p>;
  if (error) return <p className="text-sm text-red-400">Erreur : {String((error as Error).message ?? error)}</p>;
  return null;
}

export const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)} %`;
