CREATE TABLE IF NOT EXISTS proxies (
  key             text PRIMARY KEY,
  protocol        text NOT NULL,
  host            text NOT NULL,
  port            integer NOT NULL,
  user_           text,
  pass_           text,
  alive           boolean NOT NULL DEFAULT false,
  latency_ms      integer,
  remote_ip       text,
  anonymity       text,
  tls_issuer      text,
  tls_mitm        boolean DEFAULT false,
  supports_tls    boolean DEFAULT false,
  error           text,
  first_seen      timestamptz NOT NULL DEFAULT now(),
  last_ok         timestamptz,
  last_check      timestamptz NOT NULL DEFAULT now(),
  checks          integer NOT NULL DEFAULT 0,
  ok_checks       integer NOT NULL DEFAULT 0,
  fails           integer NOT NULL DEFAULT 0,
  country         text,
  city            text,
  asn             integer,
  org             text,
  uptime1h        integer[] NOT NULL DEFAULT ARRAY[0,0],
  uptime24h       integer[] NOT NULL DEFAULT ARRAY[0,0],
  uptime7d        integer[] NOT NULL DEFAULT ARRAY[0,0],
  uptime30d       integer[] NOT NULL DEFAULT ARRAY[0,0],
  latency_samples integer[] NOT NULL DEFAULT ARRAY[]::integer[],
  seen_by         text[] NOT NULL DEFAULT ARRAY[]::text[],
  disabled_until  timestamptz
);

CREATE INDEX IF NOT EXISTS proxies_last_ok_idx ON proxies (last_ok DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS proxies_protocol_idx ON proxies (protocol, alive);
CREATE INDEX IF NOT EXISTS proxies_country_idx ON proxies (country);
