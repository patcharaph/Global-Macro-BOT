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

create table if not exists backtest_runs (
  id                    bigserial primary key,
  run_id                uuid        not null unique,
  run_date              date        not null default current_date,
  sharpe_ratio          float8,
  max_drawdown          float8,
  annual_return         float8,
  benchmark_sharpe      float8,
  benchmark_return      float8,
  outperforms_benchmark boolean,
  created_at            timestamptz not null default now()
);

create index if not exists idx_backtest_runs_date
  on backtest_runs (run_date desc);
