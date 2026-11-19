import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ApiError, api } from "./api";
import { Ads, Connections, Events, Login, Marketing, Menu, Overview, Profiles, Reviews, Settings, Social } from "./screens";
import { Shell } from "./ui";

export function App() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api<{ email: string }>("/api/me")
      .then((me) => setEmail(me.email))
      .catch((exc) => {
        if (exc instanceof ApiError && exc.status === 401) setEmail(null);
      })
      .finally(() => setReady(true));
  }, []);

  if (!ready) {
    return <div className="grid min-h-screen place-items-center text-[var(--muted)]">Opening the house book…</div>;
  }
  if (!email) {
    return (
      <Routes>
        <Route path="*" element={<Login onSuccess={setEmail} />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route element={<Shell email={email} onLogout={async () => { await api("/api/logout", { method: "POST" }); setEmail(null); }} />}>
        <Route index element={<Overview />} />
        <Route path="profiles" element={<Profiles />} />
        <Route path="menu" element={<Menu />} />
        <Route path="social" element={<Social />} />
        <Route path="marketing" element={<Marketing />} />
        <Route path="ads" element={<Ads />} />
        <Route path="reviews" element={<Reviews />} />
        <Route path="events" element={<Events />} />
        <Route path="connections" element={<Connections />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
