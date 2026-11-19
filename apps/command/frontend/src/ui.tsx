import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";

const NAV = [
  ["/", "Overview"],
  ["/profiles", "Profiles"],
  ["/menu", "Menu"],
  ["/social", "Social"],
  ["/marketing", "Marketing"],
  ["/ads", "Advertising"],
  ["/reviews", "Reviews"],
  ["/events", "Events"],
  ["/settings", "Settings"],
];

export function Shell({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("survey-theme", dark ? "dark" : "light");
    const theme = document.querySelector('meta[name="theme-color"]');
    theme?.setAttribute("content", dark ? "#13110f" : "#f3efe7");
  }, [dark]);

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="sticky top-0 z-20 hidden h-screen flex-col border-r border-[var(--line)] bg-[var(--card)] px-4 py-5 backdrop-blur md:flex">
        <Brand />
        <nav className="mt-8 flex flex-1 flex-col gap-1">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={linkClass}>
              {label}
            </NavLink>
          ))}
        </nav>
        <footer className="space-y-3 text-sm text-[var(--muted)]">
          <button className="btn secondary w-full" onClick={() => setDark((value) => !value)} type="button">
            {dark ? "Light room" : "Dark room"}
          </button>
          <div className="flex items-center justify-between gap-2">
            <span className="truncate">{email}</span>
            <button className="btn secondary" onClick={onLogout} type="button">Sign out</button>
          </div>
        </footer>
      </aside>
      <div className="min-w-0">
        <header className="flex items-center justify-between border-b border-[var(--line)] px-4 py-3 md:hidden">
          <Brand />
          <button className="btn secondary" type="button" onClick={() => setOpen((value) => !value)}>Menu</button>
        </header>
        {open && (
          <nav className="grid gap-1 border-b border-[var(--line)] p-3 md:hidden">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} className={linkClass} onClick={() => setOpen(false)}>
                {label}
              </NavLink>
            ))}
            <button className="btn secondary" type="button" onClick={() => setDark((value) => !value)}>
              {dark ? "Light room" : "Dark room"}
            </button>
          </nav>
        )}
        <main className="rise mx-auto max-w-6xl px-4 py-6 pb-16 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div>
      <div className="font-display text-2xl leading-none">Survey <em>Café</em></div>
      <div className="mt-1 text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Command</div>
    </div>
  );
}

function linkClass({ isActive }: { isActive: boolean }) {
  return `rounded-xl px-3 py-2 text-sm ${isActive ? "bg-[var(--accent-soft)] text-[var(--ink)]" : "text-[var(--muted)] hover:bg-[var(--accent-soft)]"}`;
}

export function PageTitle({ kicker, title, text }: { kicker: string; title: string; text: string }) {
  return (
    <header className="mb-6 max-w-3xl">
      <div className="text-xs uppercase tracking-[0.18em] text-[var(--saffron)]">{kicker}</div>
      <h1 className="mt-1 font-display text-4xl font-medium tracking-tight">{title}</h1>
      <p className="mt-2 text-[var(--muted)]">{text}</p>
    </header>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-3xl border border-[var(--line)] bg-[var(--card)] p-4 shadow-card ${className}`}>
      {children}
    </section>
  );
}

export function Banner({ text, tone = "info" }: { text: string; tone?: "info" | "bad" }) {
  return (
    <p className={`rounded-2xl border px-3 py-2 text-sm ${tone === "bad" ? "border-[var(--bad)] text-[var(--bad)]" : "border-[var(--line)] text-[var(--muted)]"}`}>
      {text}
    </p>
  );
}

export function StatusDot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? "bg-[var(--saffron)]" : ok ? "bg-[var(--good)]" : "bg-[var(--bad)]";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

export function Bars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  if (!rows.length) return <p className="text-sm text-[var(--muted)]">Nothing to chart yet.</p>;
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="mb-1 flex justify-between text-xs text-[var(--muted)]">
            <span>{row.label}</span>
            <span className="tabular-nums text-[var(--ink)]">{row.value}</span>
          </div>
          <div className="h-2 rounded-full bg-[var(--line)]">
            <div className="h-2 rounded-full bg-[var(--accent)] transition-[width] duration-500" style={{ width: `${(row.value / max) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function useError() {
  const [error, setError] = useState("");
  return {
    error,
    async run(task: () => Promise<void>) {
      setError("");
      try {
        await task();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Something went wrong");
      }
    },
  };
}
