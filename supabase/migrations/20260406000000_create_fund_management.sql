-- ============================================================================
-- Migration: 20260406000000_create_fund_management
-- Description: Create fund (SPC) management, lease contracts, SAB,
--              fee records, and distribution tables
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: funds
-- ---------------------------------------------------------------------------
CREATE TABLE public.funds (
  id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_name               text        NOT NULL,
  fund_code               text        NOT NULL UNIQUE,
  manager_user_id         uuid        REFERENCES public.users(id),
  establishment_date      date        NOT NULL,
  operation_start_date    date,
  operation_end_date      date,
  target_yield_rate       numeric(6,4)  CHECK (target_yield_rate >= 0),
  operation_term_months   integer       CHECK (operation_term_months > 0),
  total_fundraise_amount  bigint        CHECK (total_fundraise_amount >= 0),
  current_cash_balance    bigint      NOT NULL DEFAULT 0,
  reserve_amount          bigint      NOT NULL DEFAULT 0 CHECK (reserve_amount >= 0),
  status                  text        NOT NULL DEFAULT 'preparing'
                                      CHECK (status IN (
                                        'preparing', 'fundraising', 'active',
                                        'liquidating', 'closed'
                                      )),
  description             text,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.funds IS 'Fund (SPC) master — holds truck assets and manages leaseback operations';
COMMENT ON COLUMN public.funds.target_yield_rate IS 'Target annual yield as decimal (e.g. 0.0850 = 8.5%)';
COMMENT ON COLUMN public.funds.current_cash_balance IS 'Current cash position in JPY';

CREATE INDEX idx_funds_status ON public.funds (status);
CREATE INDEX idx_funds_manager ON public.funds (manager_user_id);

CREATE TRIGGER trg_funds_updated_at
  BEFORE UPDATE ON public.funds
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: fund_investors
-- ---------------------------------------------------------------------------
CREATE TABLE public.fund_investors (
  id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id                 uuid        NOT NULL REFERENCES public.funds(id),
  investor_name           text        NOT NULL,
  investor_type           text        NOT NULL
                                      CHECK (investor_type IN ('institutional', 'individual')),
  investor_contact_email  text,
  investment_amount       bigint      NOT NULL CHECK (investment_amount > 0),
  investment_ratio        numeric(8,6)  CHECK (investment_ratio BETWEEN 0 AND 1),
  investment_date         date,
  cumulative_distribution bigint      NOT NULL DEFAULT 0 CHECK (cumulative_distribution >= 0),
  is_active               boolean     NOT NULL DEFAULT true,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_fund_investors UNIQUE (fund_id, investor_name)
);

COMMENT ON TABLE public.fund_investors IS 'Investor allocations per fund — tracks capital commitment and distributions';
COMMENT ON COLUMN public.fund_investors.investment_ratio IS 'Ownership ratio as decimal (e.g. 0.250000 = 25%)';

CREATE INDEX idx_fund_investors_fund_id ON public.fund_investors (fund_id);

CREATE TRIGGER trg_fund_investors_updated_at
  BEFORE UPDATE ON public.fund_investors
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: lease_contracts
-- ---------------------------------------------------------------------------
CREATE TABLE public.lease_contracts (
  id                          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id                     uuid        NOT NULL REFERENCES public.funds(id),
  contract_number             text        NOT NULL UNIQUE,
  lessee_company_name         text        NOT NULL,
  lessee_corporate_number     text,
  lessee_contact_person       text,
  lessee_contact_email        text,
  lessee_contact_phone        text,
  contract_start_date         date        NOT NULL,
  contract_end_date           date        NOT NULL,
  lease_term_months           integer     NOT NULL CHECK (lease_term_months > 0),
  monthly_lease_amount        bigint      NOT NULL CHECK (monthly_lease_amount > 0),
  monthly_lease_amount_tax_incl bigint    NOT NULL CHECK (monthly_lease_amount_tax_incl > 0),
  tax_rate                    numeric(5,4) NOT NULL DEFAULT 0.1000
                                          CHECK (tax_rate >= 0),
  residual_value              bigint      DEFAULT 0 CHECK (residual_value >= 0),
  payment_day                 integer     NOT NULL DEFAULT 25
                                          CHECK (payment_day BETWEEN 1 AND 31),
  status                      text        NOT NULL DEFAULT 'draft'
                                          CHECK (status IN (
                                            'draft', 'active', 'overdue',
                                            'terminated', 'completed'
                                          )),
  termination_date            date,
  termination_reason          text,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_contract_dates CHECK (contract_end_date > contract_start_date)
);

COMMENT ON TABLE public.lease_contracts IS 'Leaseback contracts — transport companies sub-lease trucks from the fund';
COMMENT ON COLUMN public.lease_contracts.monthly_lease_amount IS 'Monthly lease payment excluding tax (JPY)';
COMMENT ON COLUMN public.lease_contracts.tax_rate IS 'Consumption tax rate as decimal (e.g. 0.1000 = 10%)';

CREATE INDEX idx_lease_contracts_fund_id ON public.lease_contracts (fund_id);
CREATE INDEX idx_lease_contracts_status ON public.lease_contracts (status);
CREATE INDEX idx_lease_contracts_lessee ON public.lease_contracts (lessee_company_name);
CREATE INDEX idx_lease_contracts_end_date ON public.lease_contracts (contract_end_date);

CREATE TRIGGER trg_lease_contracts_updated_at
  BEFORE UPDATE ON public.lease_contracts
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: lease_payments
-- ---------------------------------------------------------------------------
CREATE TABLE public.lease_payments (
  id                        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  lease_contract_id         uuid        NOT NULL REFERENCES public.lease_contracts(id) ON DELETE CASCADE,
  payment_sequence          integer     NOT NULL CHECK (payment_sequence > 0),
  scheduled_date            date        NOT NULL,
  scheduled_amount          bigint      NOT NULL CHECK (scheduled_amount > 0),
  scheduled_amount_tax_incl bigint      NOT NULL CHECK (scheduled_amount_tax_incl > 0),
  status                    text        NOT NULL DEFAULT 'scheduled'
                                        CHECK (status IN (
                                          'scheduled', 'paid', 'partial',
                                          'overdue', 'waived'
                                        )),
  actual_payment_date       date,
  actual_amount             bigint      CHECK (actual_amount >= 0),
  overdue_days              integer     NOT NULL DEFAULT 0 CHECK (overdue_days >= 0),
  notes                     text,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_lease_payment_seq UNIQUE (lease_contract_id, payment_sequence)
);

COMMENT ON TABLE public.lease_payments IS 'Payment schedule and actuals for each lease contract';

CREATE INDEX idx_lease_payments_contract ON public.lease_payments (lease_contract_id);
CREATE INDEX idx_lease_payments_scheduled_date ON public.lease_payments (scheduled_date);
CREATE INDEX idx_lease_payments_status ON public.lease_payments (status);

-- Composite index for overdue detection queries
CREATE INDEX idx_lease_payments_overdue_detection
  ON public.lease_payments (scheduled_date, status)
  WHERE status IN ('scheduled', 'overdue');

CREATE TRIGGER trg_lease_payments_updated_at
  BEFORE UPDATE ON public.lease_payments
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: secured_asset_blocks
-- ---------------------------------------------------------------------------
CREATE TABLE public.secured_asset_blocks (
  id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id                 uuid        NOT NULL REFERENCES public.funds(id),
  lease_contract_id       uuid        REFERENCES public.lease_contracts(id),
  vehicle_id              uuid        REFERENCES public.vehicles(id),
  sab_number              text        NOT NULL UNIQUE,
  vehicle_description     text,
  acquisition_price       bigint      NOT NULL CHECK (acquisition_price > 0),
  acquisition_date        date        NOT NULL,
  b2b_wholesale_valuation bigint      CHECK (b2b_wholesale_valuation >= 0),
  option_adjustment       bigint      NOT NULL DEFAULT 0,
  adjusted_valuation      bigint      CHECK (adjusted_valuation >= 0),
  ltv_ratio               numeric(6,4)  CHECK (ltv_ratio >= 0),
  valuation_date          date,
  status                  text        NOT NULL DEFAULT 'held'
                                      CHECK (status IN (
                                        'held', 'leased', 'disposing', 'disposed'
                                      )),
  disposal_price          bigint      CHECK (disposal_price >= 0),
  disposal_date           date,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.secured_asset_blocks IS 'SAB — individual vehicle assets held by a fund with real-time valuation';
COMMENT ON COLUMN public.secured_asset_blocks.b2b_wholesale_valuation IS 'Current B2B wholesale (auction/boka) valuation in JPY';
COMMENT ON COLUMN public.secured_asset_blocks.option_adjustment IS 'Option-adjusted valuation delta (can be positive or negative)';
COMMENT ON COLUMN public.secured_asset_blocks.ltv_ratio IS 'Loan-to-Value = acquisition_price / adjusted_valuation';

CREATE INDEX idx_sab_fund_id ON public.secured_asset_blocks (fund_id);
CREATE INDEX idx_sab_lease_contract ON public.secured_asset_blocks (lease_contract_id);
CREATE INDEX idx_sab_vehicle ON public.secured_asset_blocks (vehicle_id);
CREATE INDEX idx_sab_status ON public.secured_asset_blocks (status);

CREATE TRIGGER trg_sab_updated_at
  BEFORE UPDATE ON public.secured_asset_blocks
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: fee_records
-- ---------------------------------------------------------------------------
CREATE TABLE public.fee_records (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id               uuid        NOT NULL REFERENCES public.funds(id),
  lease_contract_id     uuid        REFERENCES public.lease_contracts(id),
  sab_id                uuid        REFERENCES public.secured_asset_blocks(id),
  fee_type              text        NOT NULL
                                    CHECK (fee_type IN (
                                      'brokerage_fee', 'management_fee',
                                      'early_termination_fee', 'disposal_fee'
                                    )),
  base_amount           bigint      NOT NULL CHECK (base_amount > 0),
  fee_rate              numeric(8,6) NOT NULL CHECK (fee_rate >= 0),
  fee_amount            bigint      NOT NULL CHECK (fee_amount > 0),
  calculation_date      date        NOT NULL,
  target_period_start   date,
  target_period_end     date,
  payment_status        text        NOT NULL DEFAULT 'calculated'
                                    CHECK (payment_status IN (
                                      'calculated', 'invoiced', 'paid'
                                    )),
  notes                 text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.fee_records IS 'Fee calculations — brokerage, management, termination, and disposal fees';

CREATE INDEX idx_fee_records_fund_id ON public.fee_records (fund_id);
CREATE INDEX idx_fee_records_type ON public.fee_records (fee_type);
CREATE INDEX idx_fee_records_calc_date ON public.fee_records (calculation_date);
CREATE INDEX idx_fee_records_payment_status ON public.fee_records (payment_status);

CREATE TRIGGER trg_fee_records_updated_at
  BEFORE UPDATE ON public.fee_records
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Table: fund_distributions
-- ---------------------------------------------------------------------------
CREATE TABLE public.fund_distributions (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_id               uuid        NOT NULL REFERENCES public.funds(id),
  investor_id           uuid        NOT NULL REFERENCES public.fund_investors(id),
  distribution_date     date        NOT NULL,
  distribution_type     text        NOT NULL DEFAULT 'monthly'
                                    CHECK (distribution_type IN (
                                      'monthly', 'interim', 'final'
                                    )),
  target_period_start   date,
  target_period_end     date,
  distribution_amount   bigint      NOT NULL CHECK (distribution_amount > 0),
  annualized_yield      numeric(6,4),
  notes                 text,
  created_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.fund_distributions IS 'Distribution (dividend) records to each investor';

CREATE INDEX idx_distributions_fund_id ON public.fund_distributions (fund_id);
CREATE INDEX idx_distributions_investor ON public.fund_distributions (investor_id);
CREATE INDEX idx_distributions_date ON public.fund_distributions (distribution_date);
CREATE INDEX idx_distributions_type ON public.fund_distributions (distribution_type);
