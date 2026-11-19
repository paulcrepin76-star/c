import { useEffect, useState } from "react";
import { api, money } from "./api";
import type { CafeEvent, Campaign, Capability, Channel, MenuItem, Overview as OverviewData, Post, Profile, Review, SecretField, Status } from "./types";
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
  const [data, setData] = useState<OverviewData | null>(null);
  const { error, run } = useError();
  useEffect(() => {
    void run(async () => setData(await api<OverviewData>("/api/overview")));
    const timer = window.setInterval(() => {
      void api<OverviewData>("/api/overview").then(setData).catch(() => undefined);
    }, 30000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <>
      <PageTitle kicker="Tonight" title="The house at a glance" text="Live checks come from the containers. Counts come from records stored here. A blank chart means a platform has not reported anything yet." />
      {error && <Banner text={error} tone="bad" />}
      {data && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {data.statuses.map((row) => <StatusCard key={row.service} row={row} />)}
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <h2 className="font-display text-2xl">In the book</h2>
              <dl className="mt-3 space-y-2 text-sm">
                <Row label="Posts in progress" value={data.counts.posts_in_progress} />
                <Row label="Campaigns" value={data.counts.campaigns} />
                <Row label="Reviews awaiting a decision" value={data.counts.reviews_pending} />
                <Row label="Events" value={data.counts.events} />
                <Row label="Unread notes" value={data.counts.notifications_unread} />
              </dl>
            </Card>
            <Card>
              <h2 className="font-display text-2xl">Posts by state</h2>
              <div className="mt-3"><Bars rows={data.posts_by_status.map((row) => ({ label: row.status, value: row.count }))} /></div>
            </Card>
            <Card>
              <h2 className="font-display text-2xl">Guests and ads</h2>
              <p className="mt-3 text-sm text-[var(--muted)]">
                {data.customer_activity
                  ? `${data.customer_activity.contacts} contacts reported by Mautic.`
                  : "Mautic has not reported a contact total."}
              </p>
              <div className="mt-4">
                <Bars rows={data.ad_spend.map((row) => ({ label: row.platform, value: row.spend_cents }))} />
                {data.ad_spend.length > 0 && <p className="mt-2 text-xs text-[var(--muted)]">Bar length is spend in cents from the latest pull.</p>}
              </div>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <h2 className="font-display text-2xl">Coming up</h2>
              <ul className="mt-3 space-y-3 text-sm">
                {data.events.length === 0 && <li className="text-[var(--muted)]">No events yet.</li>}
                {data.events.map((event) => <li key={event.id}><strong>{event.name}</strong> <span className="text-[var(--muted)]">{event.starts_at || "Date not set"} · {event.status}</span></li>)}
                {data.posts.map((post) => <li key={post.id}><strong>Post {post.status}</strong> <span className="text-[var(--muted)]">{post.body.slice(0, 80) || "No caption"}</span></li>)}
              </ul>
            </Card>
            <Card>
              <h2 className="font-display text-2xl">Notes</h2>
              <ul className="mt-3 space-y-3 text-sm">
                {data.notifications.length === 0 && <li className="text-[var(--muted)]">No notes.</li>}
                {data.notifications.map((note) => (
                  <li key={note.id}>
                    <button className="text-left" type="button" onClick={() => void api(`/api/notifications/${note.id}/read`, { method: "POST" })}>
                      <strong>{note.title}</strong>
                      <div className="text-[var(--muted)]">{note.body}</div>
                    </button>
                  </li>
                ))}
                {data.reviews.slice(0, 3).map((review) => (
                  <li key={review.id} className="text-[var(--muted)]">{review.platform} · {review.rating} · {review.body.slice(0, 90)}</li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </>
  );
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

function Row({ label, value }: { label: string; value: number }) {
  return <div className="flex justify-between gap-4"><dt className="text-[var(--muted)]">{label}</dt><dd className="tabular-nums">{value}</dd></div>;
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
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const { error, run } = useError();
  async function load() { setRows((await api<{ campaigns: Campaign[] }>("/api/campaigns")).campaigns); }
  useEffect(() => { void run(load); }, []);
  return (
    <>
      <PageTitle kicker="Mautic" title="Marketing automation" text="Campaigns are created in Mautic as unpublished. n8n can queue an event draft, and it does not send the email. Turn a campaign on inside Mautic when you are ready." />
      {error && <Banner text={error} tone="bad" />}
      {note && <div className="mb-3"><Banner text={note} /></div>}
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
              <div>
                <strong>{row.name}</strong>
                <p className="text-sm text-[var(--muted)]">{row.status}{row.mautic_id ? ` · Mautic ${row.mautic_id}` : ""}</p>
                <p className="mt-1 text-sm">{row.detail}</p>
              </div>
              {row.status === "local" && <button className="btn" type="button" onClick={() => void run(async () => { const saved = await api<Campaign>(`/api/campaigns/${row.id}/push`, { method: "POST" }); setNote(saved.detail); await load(); })}>Create in Mautic</button>}
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
      <PageTitle kicker="House keys" title="Settings" text="Secrets are encrypted with COMMAND_SECRET_KEY and are not included in the export. Access the dashboard through Tailscale. Do not publish these ports on the open internet." />
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
