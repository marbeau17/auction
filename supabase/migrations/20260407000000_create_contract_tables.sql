-- Deal Stakeholders
CREATE TABLE IF NOT EXISTS deal_stakeholders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    role_type TEXT NOT NULL CHECK (role_type IN ('spc','operator','investor','end_user','guarantor','trustee')),
    company_name TEXT NOT NULL,
    representative_name TEXT,
    address TEXT,
    phone TEXT,
    email TEXT,
    registration_number TEXT,
    seal_required BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_deal_stakeholders_sim ON deal_stakeholders(simulation_id);

-- Contract Templates
CREATE TABLE IF NOT EXISTS contract_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheme_type TEXT NOT NULL DEFAULT 'standard',
    contract_name TEXT NOT NULL,
    contract_name_en TEXT,
    description TEXT,
    template_file_url TEXT,
    required_roles JSONB NOT NULL DEFAULT '{}',
    variable_mappings JSONB DEFAULT '{}',
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Deal Contracts (generated documents)
CREATE TABLE IF NOT EXISTS deal_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    template_id UUID REFERENCES contract_templates(id),
    contract_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','generated','reviewed','signed','archived')),
    document_url TEXT,
    generated_context JSONB,
    generated_at TIMESTAMPTZ,
    signed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_deal_contracts_sim ON deal_contracts(simulation_id);

-- Triggers
CREATE TRIGGER trg_deal_stakeholders_updated_at BEFORE UPDATE ON deal_stakeholders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_contract_templates_updated_at BEFORE UPDATE ON contract_templates FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_deal_contracts_updated_at BEFORE UPDATE ON deal_contracts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- RLS
ALTER TABLE deal_stakeholders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "deal_stakeholders_select" ON deal_stakeholders FOR SELECT USING (true);
CREATE POLICY "deal_stakeholders_insert" ON deal_stakeholders FOR INSERT WITH CHECK (true);
CREATE POLICY "deal_stakeholders_update" ON deal_stakeholders FOR UPDATE USING (true);

ALTER TABLE contract_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "contract_templates_select" ON contract_templates FOR SELECT USING (true);

ALTER TABLE deal_contracts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "deal_contracts_select" ON deal_contracts FOR SELECT USING (true);
CREATE POLICY "deal_contracts_insert" ON deal_contracts FOR INSERT WITH CHECK (true);

-- Seed contract templates
INSERT INTO contract_templates (scheme_type, contract_name, contract_name_en, description, required_roles, display_order) VALUES
('standard', '匿名組合契約書', 'TK Agreement', '投資家とSPC間の匿名組合契約', '{"party_a": "spc", "party_b": "investor"}', 1),
('standard', '車両売買契約書', 'Sales Agreement', '運送事業者からSPCへの車両売買契約', '{"party_a": "end_user", "party_b": "spc"}', 2),
('standard', 'マスターリース契約書', 'Master Lease Agreement', 'SPCからカーチスへのマスターリース契約', '{"party_a": "spc", "party_b": "operator"}', 3),
('standard', 'サブリース（転貸）バック契約書', 'Sub-lease Agreement', 'カーチスから運送事業者へのサブリース契約', '{"party_a": "operator", "party_b": "end_user"}', 4)
ON CONFLICT DO NOTHING;
