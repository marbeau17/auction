-- ============================================================================
-- Migration: 20260410000002_create_invoice_tables
-- Description: Create invoices, invoice line items, invoice approvals,
--              and email logs tables for the billing workflow
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: invoices
-- ---------------------------------------------------------------------------
CREATE TABLE public.invoices (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id               uuid        NOT NULL REFERENCES public.funds(id),
  lease_contract_id     uuid        NOT NULL REFERENCES public.lease_contracts(id),
  invoice_number        text        NOT NULL UNIQUE,
  billing_period_start  date        NOT NULL,
  billing_period_end    date        NOT NULL,
  subtotal              bigint      NOT NULL CHECK (subtotal >= 0),
  tax_rate              numeric(5,4) NOT NULL DEFAULT 0.1000,
  tax_amount            bigint      NOT NULL CHECK (tax_amount >= 0),
  total_amount          bigint      NOT NULL CHECK (total_amount >= 0),
  due_date              date        NOT NULL,
  status                text        NOT NULL DEFAULT 'created'
                                    CHECK (status IN (
                                      'created', 'pending_review', 'approved',
                                      'pdf_ready', 'sent', 'paid',
                                      'overdue', 'cancelled'
                                    )),
  pdf_url               text,
  notes                 text,
  sent_at               timestamptz,
  paid_at               timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_billing_period CHECK (billing_period_end > billing_period_start)
);

COMMENT ON TABLE public.invoices IS 'Invoices generated from lease contracts for billing lessees';
COMMENT ON COLUMN public.invoices.subtotal IS 'Invoice subtotal before tax in JPY';
COMMENT ON COLUMN public.invoices.tax_rate IS 'Consumption tax rate as decimal (e.g. 0.1000 = 10%)';
COMMENT ON COLUMN public.invoices.total_amount IS 'Total invoice amount including tax in JPY';

CREATE INDEX idx_invoices_fund_id ON public.invoices (fund_id);
CREATE INDEX idx_invoices_lease_contract_id ON public.invoices (lease_contract_id);
CREATE INDEX idx_invoices_status ON public.invoices (status);
CREATE INDEX idx_invoices_due_date ON public.invoices (due_date);
CREATE INDEX idx_invoices_billing_period ON public.invoices (billing_period_start, billing_period_end);

CREATE TRIGGER trg_invoices_updated_at
  BEFORE UPDATE ON public.invoices
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: invoice_line_items
-- ---------------------------------------------------------------------------
CREATE TABLE public.invoice_line_items (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id      uuid        NOT NULL REFERENCES public.invoices(id) ON DELETE CASCADE,
  description     text        NOT NULL,
  quantity        integer     NOT NULL DEFAULT 1,
  unit_price      bigint      NOT NULL,
  amount          bigint      NOT NULL,
  display_order   integer     DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.invoice_line_items IS 'Individual line items that make up an invoice';

CREATE INDEX idx_invoice_line_items_invoice_id ON public.invoice_line_items (invoice_id);

-- ---------------------------------------------------------------------------
-- Table: invoice_approvals
-- ---------------------------------------------------------------------------
CREATE TABLE public.invoice_approvals (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id        uuid        NOT NULL REFERENCES public.invoices(id) ON DELETE CASCADE,
  approver_user_id  uuid        NOT NULL REFERENCES public.users(id),
  action            text        NOT NULL
                                CHECK (action IN (
                                  'approve', 'reject', 'request_change'
                                )),
  comment           text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.invoice_approvals IS 'Approval audit trail for invoice review workflow';

CREATE INDEX idx_invoice_approvals_invoice_id ON public.invoice_approvals (invoice_id);
CREATE INDEX idx_invoice_approvals_approver ON public.invoice_approvals (approver_user_id);

-- ---------------------------------------------------------------------------
-- Table: email_logs
-- ---------------------------------------------------------------------------
CREATE TABLE public.email_logs (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id        uuid        REFERENCES public.invoices(id),
  recipient_email   text        NOT NULL,
  subject           text        NOT NULL,
  body_text         text,
  status            text        NOT NULL DEFAULT 'queued'
                                CHECK (status IN (
                                  'queued', 'sent', 'failed', 'bounced'
                                )),
  sent_at           timestamptz,
  error_message     text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.email_logs IS 'Log of all outbound emails, primarily invoice delivery';

CREATE INDEX idx_email_logs_invoice_id ON public.email_logs (invoice_id);
CREATE INDEX idx_email_logs_status ON public.email_logs (status);
CREATE INDEX idx_email_logs_recipient ON public.email_logs (recipient_email);

-- ============================================================================
-- Row Level Security
-- ============================================================================

-- invoices: authenticated users can read; admins can write
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;

CREATE POLICY invoices_select ON public.invoices
  FOR SELECT USING (true);

CREATE POLICY invoices_insert ON public.invoices
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
  );

CREATE POLICY invoices_update ON public.invoices
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY invoices_delete ON public.invoices
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- invoice_line_items: same access as parent invoices
ALTER TABLE public.invoice_line_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY invoice_line_items_select ON public.invoice_line_items
  FOR SELECT USING (true);

CREATE POLICY invoice_line_items_insert ON public.invoice_line_items
  FOR INSERT WITH CHECK (
    public.current_user_role() = 'admin'
  );

CREATE POLICY invoice_line_items_update ON public.invoice_line_items
  FOR UPDATE USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY invoice_line_items_delete ON public.invoice_line_items
  FOR DELETE USING (
    public.current_user_role() = 'admin'
  );

-- invoice_approvals: authenticated users can read; authenticated users can insert (submit approvals)
ALTER TABLE public.invoice_approvals ENABLE ROW LEVEL SECURITY;

CREATE POLICY invoice_approvals_select ON public.invoice_approvals
  FOR SELECT USING (true);

CREATE POLICY invoice_approvals_insert ON public.invoice_approvals
  FOR INSERT WITH CHECK (
    approver_user_id = auth.uid()
  );

-- email_logs: admins can read; service_role can write
ALTER TABLE public.email_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY email_logs_select ON public.email_logs
  FOR SELECT USING (
    public.current_user_role() = 'admin'
  );

CREATE POLICY email_logs_insert ON public.email_logs
  FOR INSERT WITH CHECK (
    auth.role() = 'service_role'
  );

CREATE POLICY email_logs_update ON public.email_logs
  FOR UPDATE USING (
    auth.role() = 'service_role'
  );
