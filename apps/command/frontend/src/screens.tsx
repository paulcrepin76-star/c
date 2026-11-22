import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, money } from "./api";
import type { CafeEvent, Campaign, Capability, Channel, IntegrationProof, MenuItem, Overview as OverviewData, PerformanceChart, PerformanceMetric, PerformanceReport, Post, Profile, Review, RuntimeProbe, SecretField, Status } from "./types";
import { Banner, Bars, Card, PageTitle, StatusDot, useError } from "./ui";

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

export function Login({ onSuccess }: { onSuccess: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { error, run } = useError();
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form
        className="w-full max-w-md rounded-[2rem] border border-[var(--line)] bg-[var(--card)] p-8 shadow-card"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const me = await api<{ email: string }>("/api/login", { method: "POST", body: JSON.stringify({ email, password }) });
            onSuccess(me.email);
          });
        }}
      >
        <div className="font-display text-4xl">Survey <em>Café</em></div>
        <p className="mt-2 text-sm text-[var(--muted)]">Marketing command for the dining room. Sign in with the owner account from the server environment.</p>
        <label className="mt-6 block text-sm">Email<input className="field mt-1" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" /></label>
        <label className="mt-3 block text-sm">Password<input className="field mt-1" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        {error && <div className="mt-3"><Banner text={error} tone="bad" /></div>}
        <button className="btn mt-5 w-full" type="submit">Enter</button>
      </form>
    </div>
  );
}

export function Overview() {
  const [data, setData] = useState<PerformanceReport | null>(null);
  const [statuses, setStatuses] = useState<Status[]>([]);
  const [days, setDays] = useState<7 | 30 | 90 | "custom">(30);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const { error, run } = useError();

  function query() {
    if (days === "custom") return `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
    return `days=${days}`;
  }

  async function load() {
    if (days === "custom" && (!start || !end)) {
      setData(null);
      return;
    }
    const [report, overview] = await Promise.all([
      api<PerformanceReport>(`/api/performance?${query()}`),
      api<OverviewData>("/api/overview"),
    ]);
    setData(report);
    setStatuses(overview.statuses);
  }

  useEffect(() => {
    void run(load);
  }, [days, start, end]);

  return (
    <>
      <PageTitle
        kicker="Survey Café"
        title="Marketing performance"
        text="Figures come from records stored on this server. A dash means that source has not reported a usable number. Comparisons appear only when the previous period has the same kind of observation."
      />
      {error && <Banner text={error} tone="bad" />}
      <div className="mb-4 flex flex-wrap items-end gap-2">
        {([7, 30, 90] as const).map((value) => (
          <button key={value} className={days === value ? "btn" : "btn secondary"} type="button" onClick={() => setDays(value)}>
            {value} days
          </button>
        ))}
        <button className={days === "custom" ? "btn" : "btn secondary"} type="button" onClick={() => setDays("custom")}>Custom</button>
        {days === "custom" && (
          <>
            <label className="text-xs text-[var(--muted)]">Start<input className="field mt-1" type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
            <label className="text-xs text-[var(--muted)]">End<input className="field mt-1" type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
            <span className="pb-2 text-xs text-[var(--muted)]">Custom dates are UTC calendar days.</span>
          </>
        )}
        <button
          className="btn secondary"
          type="button"
          onClick={() => {
            void run(async () => {
              if (days === "custom" && (!start || !end)) return;
              const report = await api<PerformanceReport>(`/api/performance/refresh?${query()}`, { method: "POST" });
              setData(report);
              setNote([report.refresh?.contacts.detail, report.refresh?.posts.detail].filter(Boolean).join(" "));
              const overview = await api<OverviewData>("/api/overview");
              setStatuses(overview.statuses);
            });
          }}
        >
          Refresh sources
        </button>
      </div>
      {days === "custom" && (!start || !end) && <Banner text="Choose a start date and an end date. Nothing is shown until both are set." />}
      {note && <div className="mb-4"><Banner text={note} /></div>}
      {data && (
        <div className="space-y-4">
          <p className="text-xs text-[var(--muted)]">
            {when(data.start)} through {when(data.end)}. Previous period {when(data.previous_start)} through {when(data.previous_end)}. Report built {when(data.generated_at)}.
          </p>
          {data.blockers.map((item) => <Banner key={item} text={item} tone="bad" />)}
          <div className="flex flex-wrap gap-2">
            <Link className="btn" to="/social">Social</Link>
            <Link className="btn secondary" to="/marketing">Email</Link>
            <Link className="btn secondary" to="/ads">Advertising</Link>
            <Link className="btn secondary" to="/reviews">Reviews</Link>
            <Link className="btn secondary" to="/events">Events</Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {data.kpis.map((metric) => <MetricCard key={metric.id} metric={metric} large />)}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.charts.map((chart) => <ChartCard key={chart.id} chart={chart} />)}
          </div>
          <div>
            <h2 className="mb-2 font-display text-2xl">Channels</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.channels.map((metric) => <MetricCard key={metric.id} metric={metric} />)}
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <h2 className="font-display text-2xl">Content</h2>
              <div className="mt-3 grid gap-3">
                <MetricCard metric={data.content.scheduled} />
                <MetricCard metric={data.content.published} />
                <MetricCard metric={data.content.engagement} />
              </div>
            </Card>
            <Card>
              <h2 className="font-display text-2xl">Local reputation</h2>
              <p className="mt-2 text-xs uppercase tracking-wide text-[var(--muted)]">{data.reputation.status}</p>
              <dl className="mt-3 grid grid-cols-3 gap-3 text-center">
                <ReputationStat label="Reviews" value={data.reputation.count === null ? "—" : String(data.reputation.count)} />
                <ReputationStat label="Average" value={data.reputation.average_rating === null ? "—" : data.reputation.average_rating.toFixed(2)} />
                <ReputationStat label="Unresolved" value={data.reputation.unresolved_negative === null ? "—" : String(data.reputation.unresolved_negative)} />
              </dl>
              <p className="mt-3 text-xs text-[var(--muted)]">{data.reputation.detail}</p>
              <Provenance source={data.reputation.source} refreshed={data.reputation.refreshed_at} />
              <ul className="mt-3 space-y-2 text-sm">
                {data.reputation.reviews.map((review, index) => (
                  <li key={`${review.platform}-${index}`}><strong className="capitalize">{review.platform}</strong> {review.rating} · {review.author || "No name"} <span className="text-[var(--muted)]">{review.body.slice(0, 90)}</span></li>
                ))}
              </ul>
            </Card>
          </div>
          <Card>
            <h2 className="font-display text-2xl">Action center</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">{data.actions.scope}</p>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <ActionList title="Failed posts" empty="No failed posts are stored." href="/social">
                {data.actions.failed_posts.map((row) => <li key={row.id}>{row.detail || row.body.slice(0, 100) || "Failed post"}</li>)}
              </ActionList>
              <ActionList title="Pending reviews" empty="No reviews are waiting for a decision." href="/reviews">
                {data.actions.pending_reviews.map((row) => <li key={row.id}>{row.platform} · {row.body.slice(0, 100) || "No text"}</li>)}
              </ActionList>
              <ActionList title="Unsent email drafts" empty="No local or Mautic drafts are waiting." href="/marketing">
                {data.actions.unsent_drafts.map((row) => <li key={row.id}>{row.name} · {row.status}</li>)}
              </ActionList>
              <ActionList title="Upcoming events" empty="No future events are stored." href="/events">
                {data.actions.upcoming_events.map((row) => <li key={`${row.name}-${row.starts_at}`}>{row.name} · {when(row.starts_at)}</li>)}
              </ActionList>
            </div>
          </Card>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {statuses.map((row) => <StatusCard key={row.service} row={row} />)}
          </div>
        </div>
      )}
    </>
  );
}

function MetricCard({ metric, large = false }: { metric: PerformanceMetric; large?: boolean }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm text-[var(--muted)]">{metric.label}</h3>
        <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{metric.status}</span>
      </div>
      <div className={large ? "mt-2 font-display text-4xl tabular-nums" : "mt-2 text-2xl tabular-nums"}>{figure(metric)}</div>
      <Comparison metric={metric} />
      <p className="mt-2 text-xs text-[var(--muted)]">{metric.detail}</p>
      <Provenance source={metric.source} refreshed={metric.refreshed_at} />
    </Card>
  );
}

function ChartCard({ chart }: { chart: PerformanceChart }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-display text-2xl">{chart.label}</h2>
        <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{chart.status}</span>
      </div>
      <div className="mt-3">{chart.series === "none" || chart.points.length === 0 ? <p className="text-sm text-[var(--muted)]">{chart.detail}</p> : <Series chart={chart} />}</div>
      {chart.comparison && <ChartDelta comparison={chart.comparison} />}
      <Provenance source={chart.source} refreshed={chart.refreshed_at} />
    </Card>
  );
}

function Series({ chart }: { chart: PerformanceChart }) {
  const width = 360;
  const height = 140;
  const pad = 12;
  const values = chart.points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const coords = chart.points.map((point, index) => {
    const x = chart.points.length === 1 ? width / 2 : pad + (index / (chart.points.length - 1)) * (width - pad * 2);
    const y = max === min ? height / 2 : pad + (1 - (point.value - min) / (max - min)) * (height - pad * 2);
    return { ...point, x, y };
  });
  const path = coords.map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-36 w-full text-[var(--accent)]" role="img" aria-label={chart.label}>
      {chart.series === "line" && <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />}
      {coords.map((point, index) => <circle key={`${point.at}-${index}`} cx={point.x} cy={point.y} r="3.5" fill="currentColor"><title>{`${point.label || point.at}: ${point.value}`}</title></circle>)}
    </svg>
  );
}

function Comparison({ metric }: { metric: PerformanceMetric }) {
  const comparison = metric.comparison;
  if (!comparison) return null;
  const tone = comparison.tone === "good" ? "text-[var(--good)]" : comparison.tone === "bad" ? "text-[var(--bad)]" : "text-[var(--muted)]";
  const amount = metric.unit === "cents" ? money(Math.abs(comparison.delta)) : String(Math.abs(comparison.delta));
  const sign = comparison.delta > 0 ? "+" : comparison.delta < 0 ? "−" : "";
  return <p className={`mt-1 text-sm ${tone}`}>{sign}{amount} versus the previous period</p>;
}

function ChartDelta({ comparison }: { comparison: NonNullable<PerformanceChart["comparison"]> }) {
  const tone = comparison.tone === "good" ? "text-[var(--good)]" : comparison.tone === "bad" ? "text-[var(--bad)]" : "text-[var(--muted)]";
  const sign = comparison.delta > 0 ? "+" : comparison.delta < 0 ? "−" : "";
  return <p className={`mt-2 text-sm ${tone}`}>{sign}{Math.abs(comparison.delta)} versus the previous stored total</p>;
}

function Provenance({ source, refreshed }: { source: string; refreshed: string | null }) {
  return <p className="mt-2 text-[11px] leading-4 text-[var(--muted)]">{source} Last refresh: {refreshed ? when(refreshed) : "not recorded"}.</p>;
}

function ReputationStat({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-[11px] uppercase tracking-wide text-[var(--muted)]">{label}</dt><dd className="font-display text-3xl tabular-nums">{value}</dd></div>;
}

function ActionList({ title, empty, href, children }: { title: string; empty: string; href: string; children: ReactNode }) {
  const items = Array.isArray(children) ? children : [children];
  const present = items.filter(Boolean);
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm">{title}</h3>
        <Link className="text-xs text-[var(--accent)]" to={href}>Open</Link>
      </div>
      <ul className="mt-2 space-y-2 text-sm text-[var(--muted)]">{present.length === 0 ? <li>{empty}</li> : children}</ul>
    </div>
  );
}

function figure(metric: PerformanceMetric) {
  if (metric.value === null || metric.status !== "actual") return "—";
  if (metric.unit === "cents") return money(metric.value);
  return String(metric.value);
}

function when(value: string | null) {
  if (!value) return "no successful refresh";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toLocaleString("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" })} ET`;
}

function StatusCard({ row }: { row: Status }) {
  const auth = row.authenticated === null ? "Credentials not checked" : row.authenticated ? "API accepted" : "API not accepted";
  return (
    <Card>
      <div className="flex items-center gap-2 text-sm"><StatusDot ok={row.reachable} /><span className="capitalize">{row.service}</span></div>
      <p className="mt-2 text-xs text-[var(--muted)]">{row.detail}. {auth}. {row.ms} ms.</p>
    </Card>
  );
}

export function Profiles() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [current, setCurrent] = useState<Profile | null>(null);
  const { error, run } = useError();
  async function load() {
    const body = await api<{ profiles: Profile[] }>("/api/profiles");
    setProfiles(body.profiles);
    setCurrent((prev) => body.profiles.find((row) => row.platform === prev?.platform) || body.profiles[0] || null);
  }
  useEffect(() => { void run(load); }, []);
  if (!current) return error ? <Banner text={error} tone="bad" /> : null;
  return (
    <>
      <PageTitle kicker="Listings" title="Business profiles" text="Edits stay on this server until a platform accepts them. Confirmed means the destination returned success. Manual means the owner site is still where the change has to be made." />
      {error && <Banner text={error} tone="bad" />}
      <div className="mb-4 flex flex-wrap gap-2">
        {profiles.map((profile) => (
          <button key={profile.platform} className={profile.platform === current.platform ? "btn" : "btn secondary"} type="button" onClick={() => setCurrent(profile)}>
            {profile.capability?.name || profile.platform}
          </button>
        ))}
      </div>
      <Card>
        <p className="text-sm text-[var(--muted)]">{current.capability?.summary}</p>
        <p className="mt-2 text-sm">State: <strong>{current.sync_state}</strong>{current.confirmed_at ? ` · confirmed ${current.confirmed_at}` : ""}</p>
        {current.sync_detail && <p className="mt-2 text-sm">{current.sync_detail}</p>}
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <label className="text-sm">Name<input className="field mt-1" value={current.location_name} onChange={(event) => setCurrent({ ...current, location_name: event.target.value })} /></label>
          <label className="text-sm">Phone<input className="field mt-1" value={current.phone} onChange={(event) => setCurrent({ ...current, phone: event.target.value })} /></label>
          <label className="text-sm md:col-span-2">Website<input className="field mt-1" value={current.website} onChange={(event) => setCurrent({ ...current, website: event.target.value })} /></label>
          <label className="text-sm md:col-span-2">Description<textarea className="field mt-1" value={current.description} onChange={(event) => setCurrent({ ...current, description: event.target.value })} /></label>
          <label className="text-sm md:col-span-2">Announcement<textarea className="field mt-1" value={current.announcement} onChange={(event) => setCurrent({ ...current, announcement: event.target.value })} /></label>
        </div>
        <div className="mt-4 space-y-2">
          {DAYS.map((day) => {
            const hours = current.hours[day];
            return (
              <div key={day} className="grid grid-cols-[7rem_auto_1fr_1fr] items-center gap-2 text-sm">
                <span className="capitalize">{day}</span>
                <label className="flex items-center gap-1 text-[var(--muted)]"><input type="checkbox" checked={!hours.closed} onChange={(event) => setCurrent({ ...current, hours: { ...current.hours, [day]: { ...hours, closed: !event.target.checked } } })} /> Open</label>
                <input className="field" type="time" value={hours.open} disabled={hours.closed} onChange={(event) => setCurrent({ ...current, hours: { ...current.hours, [day]: { ...hours, open: event.target.value } } })} />
                <input className="field" type="time" value={hours.close} disabled={hours.closed} onChange={(event) => setCurrent({ ...current, hours: { ...current.hours, [day]: { ...hours, close: event.target.value } } })} />
              </div>
            );
          })}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn secondary" type="button" onClick={() => void run(async () => { await api(`/api/profiles/${current.platform}`, { method: "PUT", body: JSON.stringify(current) }); await load(); })}>Save here</button>
          <button className="btn" type="button" onClick={() => void run(async () => { await api(`/api/profiles/${current.platform}`, { method: "PUT", body: JSON.stringify(current) }); await api(`/api/profiles/${current.platform}/push`, { method: "POST" }); await load(); })}>Push update</button>
        </div>
      </Card>
    </>
  );
}

export function Menu() {
  const [items, setItems] = useState<MenuItem[]>([]);
  const [note, setNote] = useState("");
  const { error, run } = useError();
  async function load() {
    setItems((await api<{ items: MenuItem[] }>("/api/menu/items")).items);
  }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Kitchen" title="Menu manager" text="Text, CSV, and text-based PDFs are read for lines that already contain a price. Photos are read only when a vision model is configured. Nothing is sent to Google or Instagram from this page." />
      {error && <Banner text={error} tone="bad" />}
      {note && <div className="mb-3"><Banner text={note} /></div>}
      <Card>
        <input className="text-sm" type="file" accept=".txt,.csv,.pdf,image/*" onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          const body = new FormData();
          body.append("file", file);
          void run(async () => {
            const saved = await api<{ detail: string; status: string }>("/api/menu/documents", { method: "POST", body });
            setNote(`${saved.status}. ${saved.detail}`);
            await load();
          });
        }} />
      </Card>
      <div className="mt-4 space-y-3">
        {items.length === 0 && <p className="text-sm text-[var(--muted)]">No menu lines yet.</p>}
        {items.map((item) => (
          <Card key={item.id}>
            <div className="grid gap-2 md:grid-cols-[1fr_8rem_auto]">
              <input className="field" aria-label="Item name" value={item.name} onChange={(event) => setItems(items.map((row) => row.id === item.id ? { ...row, name: event.target.value } : row))} />
              <input className="field" aria-label="Price in dollars" type="number" min="0" step="0.01" value={item.price_cents / 100} onChange={(event) => setItems(items.map((row) => row.id === item.id ? { ...row, price_cents: Math.round(Number(event.target.value) * 100) } : row))} />
              <button className="btn secondary" type="button" onClick={() => void run(async () => { await api(`/api/menu/items/${item.id}`, { method: "PATCH", body: JSON.stringify({ name: item.name, price_cents: item.price_cents, approved: !item.approved, description: item.description, category: item.category }) }); await load(); })}>
                {item.approved ? "Approved" : "Approve"}
              </button>
            </div>
            <p className="mt-2 text-xs text-[var(--muted)]">{money(item.price_cents)} · {item.confidence} · {item.description || "No description"}</p>
          </Card>
        ))}
      </div>
    </>
  );
}

export function Social() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelNote, setChannelNote] = useState("");
  const [body, setBody] = useState("");
  const [when, setWhen] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const { error, run } = useError();
  async function load() {
    setPosts((await api<{ posts: Post[] }>("/api/posts")).posts);
    const remote = await api<{ ok: boolean; detail: string; channels: Channel[] }>("/api/channels");
    setChannels(remote.channels);
    setChannelNote(remote.detail);
  }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Postiz" title="Social" text="A post is published only when Postiz says so. The public API allows about 30 requests an hour, so refresh is manual. Instagram needs media. TikTok needs an MP4." />
      {error && <Banner text={error} tone="bad" />}
      {channelNote && <div className="mb-3"><Banner text={channelNote} /></div>}
      <Card>
        <textarea className="field" placeholder="Caption" value={body} onChange={(event) => setBody(event.target.value)} />
        <label className="mt-3 block text-sm">Schedule<input className="field mt-1" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} /></label>
        <div className="mt-3 flex flex-wrap gap-2">
          {channels.filter((channel) => !channel.disabled).map((channel) => (
            <label key={channel.id} className="rounded-full border border-[var(--line)] px-3 py-1 text-sm">
              <input className="mr-2" type="checkbox" checked={picked.includes(channel.id)} onChange={(event) => setPicked(event.target.checked ? [...picked, channel.id] : picked.filter((id) => id !== channel.id))} />
              {channel.name} · {channel.provider}
            </label>
          ))}
          {channels.length === 0 && <span className="text-sm text-[var(--muted)]">No Postiz channels yet. Connect them in Postiz, then save the API key in Settings.</span>}
        </div>
        <button className="btn mt-4" type="button" onClick={() => void run(async () => {
          const selected = channels.filter((channel) => picked.includes(channel.id)).map((channel) => ({ integration_id: channel.id, provider: channel.provider, name: channel.name }));
          await api("/api/posts", { method: "POST", body: JSON.stringify({ body, channels: selected, scheduled_for: when ? new Date(when).toISOString() : "" }) });
          setBody("");
          setPicked([]);
          await load();
        })}>Save draft</button>
      </Card>
      <Card className="mt-4">
        <h2 className="font-display text-2xl">Calendar</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {posts.filter((post) => post.scheduled_for).length === 0 && <li className="text-[var(--muted)]">No dated posts are stored.</li>}
          {posts.filter((post) => post.scheduled_for).map((post) => (
            <li key={post.id}><strong>{post.scheduled_for}</strong> <span className="capitalize text-[var(--muted)]">{post.status}</span> {post.body.slice(0, 90)}</li>
          ))}
        </ul>
      </Card>
      <div className="mt-4 space-y-3">
        {posts.map((post) => (
          <Card key={post.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <strong className="capitalize">{post.status}</strong>
                {post.remote_state && <span className="text-sm text-[var(--muted)]"> · Postiz {post.remote_state}</span>}
                <p className="mt-1 whitespace-pre-wrap text-sm">{post.body}</p>
                <p className="mt-2 text-xs text-[var(--muted)]">{post.detail}</p>
                {post.release_url && <a className="mt-1 block text-sm underline" href={post.release_url}>{post.release_url}</a>}
              </div>
              <div className="flex flex-wrap gap-2">
                {post.status !== "published" && <button className="btn" type="button" onClick={() => void run(async () => { await api(`/api/posts/${post.id}/submit?mode=${post.scheduled_for ? "schedule" : "now"}`, { method: "POST" }); await load(); })}>Send to Postiz</button>}
                <button className="btn secondary" type="button" onClick={() => void run(async () => { await api(`/api/posts/${post.id}`, { method: "DELETE" }); await load(); })}>Delete</button>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <button className="btn secondary mt-4" type="button" onClick={() => void run(async () => { const result = await api<{ detail: string }>("/api/posts/refresh", { method: "POST" }); setChannelNote(result.detail); await load(); })}>Refresh from Postiz</button>
    </>
  );
}

export function Marketing() {
  const [rows, setRows] = useState<Campaign[]>([]);
  const [audience, setAudience] = useState<{ contacts: number | null; segments: { id: string; name: string; published: boolean }[] | null; detail: string } | null>(null);
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const { error, run } = useError();
  async function load() {
    setRows((await api<{ campaigns: Campaign[] }>("/api/campaigns")).campaigns);
    setAudience(await api("/api/audience"));
  }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Mautic" title="Marketing automation" text="Campaigns are created in Mautic as unpublished. This page cannot send or activate one. Turn a campaign on inside Mautic when you decide to. n8n can queue a draft, and it does not send the email." />
      {error && <Banner text={error} tone="bad" />}
      {note && <div className="mb-3"><Banner text={note} /></div>}
      <Card className="mb-4">
        <h2 className="font-display text-2xl">Contacts and segments</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">{audience?.detail || "Mautic has not been asked yet."}</p>
        <p className="mt-2 text-sm">{audience?.contacts === null || audience?.contacts === undefined ? "No contact total." : `${audience.contacts} contacts reported by Mautic.`}</p>
        <ul className="mt-3 space-y-1 text-sm">
          {audience?.segments === null && <li className="text-[var(--muted)]">No segment list was returned.</li>}
          {audience?.segments?.length === 0 && <li className="text-[var(--muted)]">Mautic returned an empty segment list.</li>}
          {audience?.segments?.map((segment) => <li key={segment.id || segment.name}>{segment.name} · {segment.published ? "published in Mautic" : "not published"}</li>)}
        </ul>
      </Card>
      <Card>
        <div className="grid gap-3">
          <input className="field" placeholder="Campaign name" value={name} onChange={(event) => setName(event.target.value)} />
          <input className="field" placeholder="Subject" value={subject} onChange={(event) => setSubject(event.target.value)} />
          <textarea className="field" placeholder="What the email should say" value={body} onChange={(event) => setBody(event.target.value)} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn" type="button" onClick={() => void run(async () => { await api("/api/campaigns", { method: "POST", body: JSON.stringify({ name, subject, body }) }); setName(""); setSubject(""); setBody(""); await load(); })}>Save draft</button>
          <button className="btn secondary" type="button" onClick={() => void run(async () => { const result = await api<{ detail: string; contacts: number | null }>("/api/campaigns/pull", { method: "POST" }); setNote(result.contacts === null ? result.detail : `${result.detail} Contacts: ${result.contacts}.`); await load(); })}>Pull from Mautic</button>
        </div>
      </Card>
      <div className="mt-4 space-y-3">
        {rows.map((row) => (
          <Card key={row.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <input className="field" aria-label="Campaign name" value={row.name} onChange={(event) => setRows(rows.map((item) => item.id === row.id ? { ...item, name: event.target.value } : item))} />
                <input className="field mt-2" aria-label="Subject" value={row.subject} onChange={(event) => setRows(rows.map((item) => item.id === row.id ? { ...item, subject: event.target.value } : item))} />
                <textarea className="field mt-2" aria-label="Email body" value={row.body} onChange={(event) => setRows(rows.map((item) => item.id === row.id ? { ...item, body: event.target.value } : item))} />
                <p className="mt-2 text-sm text-[var(--muted)]">{row.status}{row.mautic_id ? ` · Mautic ${row.mautic_id}` : ""}</p>
                <p className="mt-1 text-sm">{row.detail}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {row.status !== "mautic_published" && <button className="btn secondary" type="button" onClick={() => void run(async () => { const saved = await api<Campaign>(`/api/campaigns/${row.id}`, { method: "PATCH", body: JSON.stringify({ name: row.name, subject: row.subject, body: row.body }) }); setNote(saved.detail); await load(); })}>Save draft</button>}
                {row.status === "local" && <button className="btn" type="button" onClick={() => void run(async () => { const saved = await api<Campaign>(`/api/campaigns/${row.id}/push`, { method: "POST" }); setNote(saved.detail); await load(); })}>Create unpublished in Mautic</button>}
                <button className="btn secondary" type="button" onClick={() => void run(async () => { await api(`/api/campaigns/${row.id}/activate`, { method: "POST" }); })}>Activate</button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}

export function Ads() {
  const [latest, setLatest] = useState<{ platform: string; campaign_name: string; spend_cents: number; clicks: number; impressions: number; conversions: number | null; captured_at: string; detail: string }[]>([]);
  const [notes, setNotes] = useState<{ platform: string; text: string }[]>([]);
  const [caps, setCaps] = useState<Capability[]>([]);
  const [message, setMessage] = useState("");
  const { error, run } = useError();
  async function load() {
    const body = await api<{ latest: typeof latest; recommendations: typeof notes }>("/api/ads");
    setLatest(body.latest);
    setNotes(body.recommendations);
    setCaps((await api<{ capabilities: Capability[] }>("/api/capabilities")).capabilities.filter((row) => row.group === "ads"));
  }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Spend" title="Advertising" text="Numbers appear only after Google Ads or Meta returns a report. Recommendations are calculated from that report, not from a template." />
      {error && <Banner text={error} tone="bad" />}
      {message && <div className="mb-3"><Banner text={message} /></div>}
      <div className="mb-4 grid gap-3 md:grid-cols-2">
        {caps.map((cap) => <Card key={cap.id}><h2 className="font-display text-2xl">{cap.name}</h2><p className="mt-2 text-sm text-[var(--muted)]">{cap.summary}</p><p className="mt-2 text-sm">{cap.requirements}</p></Card>)}
      </div>
      <button className="btn" type="button" onClick={() => void run(async () => {
        const result = await api<{ results: { platform: string; ok: boolean; detail: string }[] }>("/api/ads/sync", { method: "POST" });
        setMessage(result.results.map((row) => `${row.platform}: ${row.detail}`).join(" "));
        await load();
      })}>Sync now</button>
      <div className="mt-4"><Bars rows={latest.map((row) => ({ label: `${row.platform} · ${row.campaign_name}`, value: row.spend_cents }))} /></div>
      <div className="mt-4 space-y-3">
        {latest.length === 0 && <p className="text-sm text-[var(--muted)]">No advertising report has been stored.</p>}
        {latest.map((row) => (
          <Card key={`${row.platform}-${row.campaign_name}`}>
            <strong>{row.campaign_name}</strong>
            <p className="text-sm text-[var(--muted)]">{row.platform} · {money(row.spend_cents)} · {row.clicks} clicks · {row.impressions} impressions · {row.conversions ?? "—"} conversions</p>
            {row.detail && <p className="mt-1 text-xs">{row.detail}</p>}
            <p className="mt-1 text-xs text-[var(--muted)]">Captured {row.captured_at}</p>
          </Card>
        ))}
        {notes.map((note) => <Banner key={note.text} text={note.text} />)}
      </div>
    </>
  );
}

export function Reviews() {
  const [rows, setRows] = useState<Review[]>([]);
  const [form, setForm] = useState({ platform: "google", author: "", rating: "5", body: "" });
  const [note, setNote] = useState("");
  const { error, run } = useError();
  async function load() { setRows((await api<{ reviews: Review[] }>("/api/reviews")).reviews); }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Guests" title="Reviews" text="Replies are drafts until you approve them. Google can receive an approved reply. Yelp excerpts can be read. Yelp and Tripadvisor replies stay on their own sites." />
      {error && <Banner text={error} tone="bad" />}
      {note && <div className="mb-3"><Banner text={note} /></div>}
      <Card>
        <div className="grid gap-2 md:grid-cols-4">
          <select className="field" value={form.platform} onChange={(event) => setForm({ ...form, platform: event.target.value })}>
            <option value="google">Google</option>
            <option value="yelp">Yelp</option>
            <option value="tripadvisor">Tripadvisor</option>
            <option value="apple">Apple</option>
          </select>
          <input className="field" placeholder="Author" value={form.author} onChange={(event) => setForm({ ...form, author: event.target.value })} />
          <input className="field" type="number" min="1" max="5" value={form.rating} onChange={(event) => setForm({ ...form, rating: event.target.value })} />
          <button className="btn" type="button" onClick={() => void run(async () => { await api("/api/reviews", { method: "POST", body: JSON.stringify({ ...form, rating: Number(form.rating) }) }); setForm({ ...form, author: "", body: "" }); await load(); })}>Add manual note</button>
        </div>
        <textarea className="field mt-2" placeholder="What the guest wrote" value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} />
        <button className="btn secondary mt-3" type="button" onClick={() => void run(async () => {
          const result = await api<{ results: { platform: string; detail: string }[] }>("/api/reviews/pull", { method: "POST" });
          setNote(result.results.map((row) => `${row.platform}: ${row.detail}`).join(" "));
          await load();
        })}>Pull where an API exists</button>
      </Card>
      <div className="mt-4 space-y-3">
        {rows.map((review) => (
          <Card key={review.id}>
            <strong>{review.author || "Guest"}</strong> <span className="text-sm text-[var(--muted)]">{review.platform} · {review.rating} · {review.source}</span>
            <p className="mt-1 text-sm">{review.body}</p>
            <textarea className="field mt-2" value={review.draft_response} onChange={(event) => setRows(rows.map((row) => row.id === review.id ? { ...row, draft_response: event.target.value } : row))} />
            <p className="mt-1 text-xs text-[var(--muted)]">{review.draft_source ? `Draft source: ${review.draft_source}. ` : ""}{review.publish_detail}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button className="btn secondary" type="button" onClick={() => void run(async () => { await api(`/api/reviews/${review.id}/draft`, { method: "POST" }); await load(); })}>Draft a reply</button>
              <button className="btn secondary" type="button" onClick={() => void run(async () => { await api(`/api/reviews/${review.id}/approval`, { method: "POST", body: JSON.stringify({ approval: "approved", draft_response: review.draft_response }) }); await load(); })}>Approve</button>
              <button className="btn" type="button" onClick={() => void run(async () => { const sent = await api<Review>(`/api/reviews/${review.id}/send`, { method: "POST" }); setNote(sent.publish_detail); await load(); })}>Send</button>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}

export function Events() {
  const [rows, setRows] = useState<CafeEvent[]>([]);
  const [form, setForm] = useState({ name: "", kind: "dinner", starts_at: "", description: "" });
  const [note, setNote] = useState("");
  const { error, run } = useError();
  async function load() { setRows((await api<{ events: CafeEvent[] }>("/api/events")).events); }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Calendar" title="Events" text="Paella nights, themed dinners, and buyouts. Queueing makes a social draft and an email draft. It does not publish either one." />
      {error && <Banner text={error} tone="bad" />}
      {note && <div className="mb-3"><Banner text={note} /></div>}
      <Card>
        <div className="grid gap-2 md:grid-cols-2">
          <input className="field" placeholder="Name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          <select className="field" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value })}>
            <option value="dinner">Themed dinner</option>
            <option value="paella">Paella night</option>
            <option value="private">Private event</option>
          </select>
          <input className="field" type="datetime-local" value={form.starts_at} onChange={(event) => setForm({ ...form, starts_at: event.target.value })} />
          <textarea className="field md:col-span-2" placeholder="Details you actually want used" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
        </div>
        <button className="btn mt-3" type="button" onClick={() => void run(async () => {
          await api("/api/events", { method: "POST", body: JSON.stringify({ ...form, starts_at: form.starts_at ? new Date(form.starts_at).toISOString() : "" }) });
          setForm({ name: "", kind: "dinner", starts_at: "", description: "" });
          await load();
        })}>Add event</button>
      </Card>
      <div className="mt-4 space-y-3">
        {rows.map((event) => (
          <Card key={event.id}>
            <strong>{event.name}</strong> <span className="text-sm text-[var(--muted)]">{event.kind} · {event.starts_at || "no date"} · {event.status}</span>
            <p className="mt-1 text-sm">{event.description}</p>
            {event.promo_text && <p className="mt-2 whitespace-pre-wrap text-sm">{event.promo_text}</p>}
            {event.promo_source && <p className="text-xs text-[var(--muted)]">Caption source: {event.promo_source}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn secondary" type="button" onClick={() => void run(async () => { const saved = await api<CafeEvent & { detail?: string }>(`/api/events/${event.id}/promo`, { method: "POST" }); setNote(saved.detail || "Caption saved."); await load(); })}>Write a caption</button>
              <button className="btn" type="button" onClick={() => void run(async () => { const queued = await api<{ published: boolean }>(`/api/events/${event.id}/queue`, { method: "POST" }); setNote(queued.published ? "Published." : "Drafts are waiting in Social and Marketing. Nothing was published."); await load(); })}>Queue drafts</button>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}

function probeWord(value: boolean | null, yes: string, no: string, unknown: string) {
  if (value === null) return unknown;
  return value ? yes : no;
}

export function Assistant() {
  const [purpose, setPurpose] = useState("social");
  const [brief, setBrief] = useState("");
  const [draft, setDraft] = useState<{ text: string; source: string; detail: string; published: boolean } | null>(null);
  const { error, run } = useError();
  return (
    <>
      <PageTitle kicker="Optional" title="Marketing assistant" text="A draft is created only when Ollama answers. Saving it keeps a local copy. Nothing is sent to Postiz, Mautic, or a review site from this page." />
      {error && <Banner text={error} tone="bad" />}
      <Card>
        <select className="field" value={purpose} onChange={(event) => setPurpose(event.target.value)}>
          <option value="social">Social post</option>
          <option value="review">Review reply</option>
          <option value="campaign">Email campaign</option>
          <option value="event">Event announcement</option>
          <option value="ideas">Ideas from the brief</option>
        </select>
        <textarea className="field mt-3" placeholder="Facts you want used. Prices and dates you do not type here will not be invented when the model is off." value={brief} onChange={(event) => setBrief(event.target.value)} />
        <button className="btn mt-3" type="button" onClick={() => void run(async () => setDraft(await api("/api/assistant/draft", { method: "POST", body: JSON.stringify({ purpose, brief }) })))}>Draft</button>
        {draft && (
          <div className="mt-4">
            <p className="text-sm text-[var(--muted)]">{draft.detail} Source: {draft.source}. Published: {draft.published ? "yes" : "no"}.</p>
            <textarea className="field mt-2" value={draft.text} onChange={(event) => setDraft({ ...draft, text: event.target.value })} />
            <button className="btn secondary mt-3" type="button" disabled={!draft.text} onClick={() => void run(async () => {
              const saved = await api<{ published: boolean }>("/api/assistant/save", { method: "POST", body: JSON.stringify({ purpose, text: draft.text }) });
              setDraft({ ...draft, detail: saved.published ? "Published." : "Saved as a draft. Nothing was published.", published: saved.published });
            })}>Save draft for approval</button>
          </div>
        )}
      </Card>
    </>
  );
}

export function Connections() {
  const [rows, setRows] = useState<IntegrationProof[]>([]);
  const [runtime, setRuntime] = useState<RuntimeProbe[]>([]);
  const [note, setNote] = useState("");
  const { error, run } = useError();
  useEffect(() => {
    void run(async () => {
      const body = await api<{ note: string; live_calls_made: boolean; integrations: IntegrationProof[]; runtime: RuntimeProbe[] }>("/api/integrations");
      setNote(body.note);
      setRows(body.integrations);
      setRuntime(body.runtime);
    });
  }, []);
  return (
    <>
      <PageTitle kicker="Proof" title="Connections" text="Configured, reachable, and authorized describe this server right now. Genuinely tested stays no until a real account action succeeds. A unit test does not change that." />
      {error && <Banner text={error} tone="bad" />}
      {note && <Banner text={note} />}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {runtime.map((row) => (
          <Card key={row.id}>
            <h2 className="font-display text-2xl">{row.name}</h2>
            <dl className="mt-2 space-y-1 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Configured</dt><dd>{row.configured ? "yes" : "no"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Reachable</dt><dd>{probeWord(row.reachable, "yes", "no", "not probed")}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Authorized</dt><dd>{probeWord(row.authorized, "yes", "no", "not probed")}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Genuinely tested</dt><dd>{row.genuinely_tested ? "yes" : "no"}</dd></div>
            </dl>
            <p className="mt-2 text-sm text-[var(--muted)]">{row.detail}</p>
          </Card>
        ))}
      </div>
      <div className="mt-4 space-y-3">
        {rows.map((row) => (
          <Card key={row.id}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-2xl">{row.name}</h2>
              <span className="text-xs uppercase tracking-[0.14em] text-[var(--muted)]">{row.code} · {row.verification}</span>
            </div>
            <p className="mt-2 text-sm">{row.authorized_api_test ? "Authorized API test passed." : "No authorized API test has passed."}</p>
            <p className="mt-2 text-sm text-[var(--muted)]">{row.unit_test}</p>
            <p className="mt-2 text-sm">{row.still_needed}</p>
          </Card>
        ))}
      </div>
    </>
  );
}

export function Settings() {
  const [fields, setFields] = useState<SecretField[]>([]);
  const [system, setSystem] = useState<Record<string, string | boolean>>({});
  const [audit, setAudit] = useState<{ id: number; action: string; detail: string; created_at: string }[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const { error, run } = useError();
  async function load() {
    const body = await api<{ fields: SecretField[]; system: Record<string, string | boolean> }>("/api/settings");
    setFields(body.fields);
    setSystem(body.system);
    setAudit((await api<{ audit: typeof audit }>("/api/audit")).audit);
  }
  useEffect(() => { void run(load); }, []);
  const groups = [...new Set(fields.map((field) => field.group))];
  return (
    <>
      <PageTitle kicker="House keys" title="Settings" text="Secrets are encrypted with COMMAND_SECRET_KEY and are not included in the export. The session cookie is HttpOnly, SameSite lax, and lasts 12 hours. Use Tailscale for this dashboard. Public HTTPS is a separate Caddy edge for Mautic and Postiz only, and it is not started with the dashboard." />
      {error && <Banner text={error} tone="bad" />}
      <Card className="mb-4">
        <h2 className="font-display text-2xl">Health</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">Database {String(system.database)} · data {String(system.data_dir)} · local model {system.ollama ? "configured" : "not configured"} · vision {system.vision ? "configured" : "not configured"}</p>
        <a className="btn secondary mt-3 inline-block" href="/api/admin/export">Download records</a>
      </Card>
      {groups.map((group) => (
        <Card key={group} className="mb-4">
          <h2 className="font-display text-2xl">{group}</h2>
          <div className="mt-3 space-y-3">
            {fields.filter((field) => field.group === group).map((field) => (
              <label key={field.name} className="block text-sm">
                {field.label} {field.configured && <span className="text-[var(--good)]">saved</span>}
                <input
                  className="field mt-1"
                  type={field.secret ? "password" : "text"}
                  placeholder={field.secret && field.configured ? "Saved. Type to replace." : field.hint}
                  value={drafts[field.name] ?? (field.secret ? "" : field.value)}
                  onChange={(event) => setDrafts({ ...drafts, [field.name]: event.target.value })}
                />
                <button className="btn secondary mt-2" type="button" onClick={() => void run(async () => {
                  const value = drafts[field.name] ?? "";
                  if (!value) throw new Error(field.secret ? "Type a replacement. Leave the box blank to keep the saved secret." : "Type a value first.");
                  await api("/api/settings/secrets", { method: "PUT", body: JSON.stringify({ name: field.name, value }) });
                  setDrafts({ ...drafts, [field.name]: "" });
                  await load();
                })}>Save</button>
              </label>
            ))}
          </div>
        </Card>
      ))}
      <Card>
        <h2 className="font-display text-2xl">Recent actions</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {audit.length === 0 && <li className="text-[var(--muted)]">No actions yet.</li>}
          {audit.map((row) => <li key={row.id}><span className="text-[var(--muted)]">{row.created_at}</span> {row.action} {row.detail}</li>)}
        </ul>
      </Card>
    </>
  );
}
