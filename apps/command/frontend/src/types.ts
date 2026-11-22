export type RuntimeProbe = {
  id: string;
  name: string;
  configured: boolean;
  reachable: boolean | null;
  authorized: boolean | null;
  genuinely_tested: boolean;
  detail: string;
};

export type IntegrationProof = {
  id: string;
  name: string;
  code: string;
  verification: string;
  unit_test: string;
  still_needed: string;
  live_verified: boolean;
  authorized_api_test: boolean;
};

export type Status = {
  service: string;
  reachable: boolean;
  authenticated: boolean | null;
  detail: string;
  ms: number;
};

export type Capability = {
  id: string;
  name: string;
  group: string;
  listing_write: string;
  review_read: string;
  review_reply: string;
  posts: string;
  summary: string;
  requirements: string;
  ads_read?: string;
};

export type Profile = {
  platform: string;
  location_name: string;
  description: string;
  phone: string;
  website: string;
  hours: Record<string, { closed: boolean; open: string; close: string }>;
  holiday_hours: { date: string; closed?: boolean; open?: string; close?: string }[];
  announcement: string;
  sync_state: string;
  sync_detail: string;
  confirmed_at: string | null;
  capability: Capability | null;
};

export type MenuItem = {
  id: number;
  name: string;
  description: string;
  price_cents: number;
  category: string;
  confidence: string;
  approved: boolean;
};

export type Post = {
  id: number;
  body: string;
  channels: { integration_id: string; provider: string; name?: string }[];
  media: { filename?: string; content_type?: string }[];
  scheduled_for: string;
  status: string;
  remote_state: string;
  release_url: string;
  detail: string;
};

export type Channel = { id: string; provider: string; name: string; disabled: boolean };

export type Campaign = {
  id: number;
  name: string;
  subject: string;
  body: string;
  status: string;
  mautic_id: string;
  detail: string;
};

export type Review = {
  id: number;
  platform: string;
  author: string;
  rating: number;
  body: string;
  source: string;
  draft_response: string;
  draft_source: string;
  approval: string;
  publish_state: string;
  publish_detail: string;
};

export type CafeEvent = {
  id: number;
  name: string;
  kind: string;
  starts_at: string;
  ends_at: string;
  description: string;
  capacity: number | null;
  promo_text: string;
  promo_source: string;
  status: string;
};

export type Overview = {
  generated_at: string;
  statuses: Status[];
  customer_activity: { source: string; contacts: number; detail: string } | null;
  counts: Record<string, number>;
  posts_by_status: { status: string; count: number }[];
  posts: Post[];
  scheduled_posts: Post[];
  published_posts: Post[];
  failed_posts: Post[];
  engagement: null;
  campaigns: Campaign[];
  reviews: Review[];
  events: CafeEvent[];
  notifications: { id: number; title: string; body: string; read: boolean; created_at: string }[];
  ad_spend: { platform: string; spend_cents: number }[];
};

export type PerformanceMetric = {
  id: string;
  label: string;
  status: string;
  value: number | null;
  unit: string;
  source: string;
  refreshed_at: string | null;
  detail: string;
  comparison: { previous: number; delta: number; tone: "good" | "bad" | "neutral" } | null;
};

export type PerformanceChart = {
  id: string;
  label: string;
  status: string;
  series: string;
  points: { at: string; value: number; label?: string }[];
  source: string;
  refreshed_at: string | null;
  detail: string;
  comparison?: PerformanceMetric["comparison"];
};

export type PerformanceReport = {
  generated_at: string;
  start: string;
  end: string;
  previous_start: string;
  previous_end: string;
  kpis: PerformanceMetric[];
  charts: PerformanceChart[];
  channels: PerformanceMetric[];
  content: { scheduled: PerformanceMetric; published: PerformanceMetric; engagement: PerformanceMetric };
  reputation: {
    status: string;
    count: number | null;
    average_rating: number | null;
    unresolved_negative: number | null;
    source: string;
    refreshed_at: string | null;
    detail: string;
    reviews: { platform: string; author: string; rating: number; body: string }[];
  };
  actions: {
    scope: string;
    failed_posts: { id: number; body: string; detail: string }[];
    pending_reviews: { id: number; platform: string; body: string }[];
    unsent_drafts: { id: number; name: string; status: string }[];
    upcoming_events: { name: string; starts_at: string | null; status: string }[];
  };
  blockers: string[];
  refresh?: { contacts: { ok: boolean; detail: string }; posts: { ok: boolean; detail: string } };
};

export type SecretField = {
  group: string;
  name: string;
  label: string;
  secret: boolean;
  hint: string;
  configured: boolean;
  value: string;
};
