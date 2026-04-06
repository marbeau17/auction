-- ============================================================================
-- Migration: 20260401000005_create_scraping_logs
-- Description: Create scraping_logs and vehicle_price_history tables
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: scraping_logs
-- ---------------------------------------------------------------------------
CREATE TABLE public.scraping_logs (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  source_site     text        NOT NULL,
  status          text        NOT NULL DEFAULT 'running'
                              CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  total_pages     int,
  processed_pages int         NOT NULL DEFAULT 0,
  new_records     int         NOT NULL DEFAULT 0,
  updated_records int         NOT NULL DEFAULT 0,
  skipped_records int         NOT NULL DEFAULT 0,
  error_count     int         NOT NULL DEFAULT 0,
  error_details   jsonb,
  triggered_by    text        NOT NULL DEFAULT 'cron',
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.scraping_logs IS 'Audit log for scraping job runs';

-- Indexes
CREATE INDEX idx_scraping_logs_source_site ON public.scraping_logs (source_site);
CREATE INDEX idx_scraping_logs_status      ON public.scraping_logs (status);
CREATE INDEX idx_scraping_logs_started_at  ON public.scraping_logs (started_at DESC);

-- Trigger
CREATE TRIGGER trg_scraping_logs_updated_at
  BEFORE UPDATE ON public.scraping_logs
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: vehicle_price_history
-- ---------------------------------------------------------------------------
CREATE TABLE public.vehicle_price_history (
  id                  bigserial       PRIMARY KEY,
  source_site         varchar(50)     NOT NULL,
  source_vehicle_id   varchar(100)    NOT NULL,
  price_yen           int             NOT NULL,
  price_tax_included  boolean,
  observed_at         timestamptz     NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.vehicle_price_history
  IS 'Point-in-time price snapshots for tracking price changes over time';

-- Indexes
CREATE INDEX idx_vehicle_price_history_source
  ON public.vehicle_price_history (source_site, source_vehicle_id);
CREATE INDEX idx_vehicle_price_history_observed_at
  ON public.vehicle_price_history (observed_at DESC);
