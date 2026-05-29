-- รัน SQL นี้ใน Supabase SQL Editor (supabase.com → project → SQL Editor)

create table if not exists raw_series (
  id        bigserial primary key,
  series_id text      not null,
  date      date      not null,
  value     float8,
  unique (series_id, date)
);

create index if not exists idx_raw_series_lookup
  on raw_series (series_id, date);
