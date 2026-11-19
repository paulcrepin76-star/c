export type IntegrationProof = {
  id: string;
  name: string;
  code: string;
  verification: string;
  unit_test: string;
  still_needed: string;
  live_verified: boolean;
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
  campaigns: Campaign[];
  reviews: Review[];
  events: CafeEvent[];
  notifications: { id: number; title: string; body: string; read: boolean; created_at: string }[];
  ad_spend: { platform: string; spend_cents: number }[];
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
