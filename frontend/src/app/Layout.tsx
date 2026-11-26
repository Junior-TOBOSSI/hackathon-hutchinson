import { NavLink, Outlet } from "react-router";

import { config } from "./config";

const spaces = [
  { to: "/operator", label: "Opérateur", api: "Edge" },
  { to: "/supervisor", label: "Superviseur", api: "Core" },
  { to: "/ai-leader", label: "AI Leader", api: "Core" },
];

export function Layout() {
  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-argos-line bg-argos-panel px-6 py-3">
        <span className="text-lg font-semibold tracking-widest text-argos-cyan">ARGOS</span>
        <nav className="flex gap-2">
          {spaces.map((s) => (
            <NavLink
              key={s.to}
              to={s.to}
              className={({ isActive }) =>
                `rounded px-3 py-1 text-sm ${isActive ? "bg-argos-cyan text-argos-night" : "hover:bg-argos-line"}`
              }
            >
              {s.label} <span className="text-xs opacity-60">({s.api})</span>
            </NavLink>
          ))}
        </nav>
        <span
          className={`ml-auto rounded px-2 py-0.5 text-xs font-semibold ${
            config.mode === "mock" ? "bg-amber-500 text-black" : "bg-emerald-600"
          }`}
          title={`Edge: ${config.edgeBaseUrl} · Core: ${config.coreBaseUrl}`}
        >
          {config.mode === "mock" ? "MODE MOCK — données simulées" : "LIVE"}
        </span>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  );
}
