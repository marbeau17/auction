-- Migration: Expand stakeholder roles and add new contract templates
-- Date: 2026-04-10

-- 1. Expand deal_stakeholders role_type constraint to include new roles
ALTER TABLE deal_stakeholders DROP CONSTRAINT IF EXISTS deal_stakeholders_role_type_check;
ALTER TABLE deal_stakeholders ADD CONSTRAINT deal_stakeholders_role_type_check
    CHECK (role_type IN (
        'spc', 'operator', 'investor', 'end_user', 'guarantor', 'trustee',
        'private_placement_agent', 'asset_manager', 'accounting_firm', 'accounting_delegate'
    ));

-- 2. Add stakeholder_role column to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS stakeholder_role TEXT;

-- 3. Insert 5 additional contract templates
INSERT INTO contract_templates (scheme_type, contract_name, contract_name_en, description, required_roles, display_order) VALUES
('standard', '私募取扱業務契約書', 'Private Placement Agreement', '私募取扱業者との業務委託契約', '{"party_a": "spc", "party_b": "private_placement_agent"}', 5),
('standard', '顧客紹介業務契約書', 'Customer Referral Agreement', '顧客紹介に関する業務委託契約', '{"party_a": "spc", "party_b": "asset_manager"}', 6),
('standard', 'アセットマネジメント契約書', 'Asset Management Agreement', 'アセットマネジメントに関する業務委託契約', '{"party_a": "spc", "party_b": "asset_manager"}', 7),
('standard', '会計事務委託契約書（会計事務所）', 'Accounting Services Agreement (Firm)', '会計事務所への事務委託契約', '{"party_a": "spc", "party_b": "accounting_firm"}', 8),
('standard', '会計事務委託契約書（一般社団法人）', 'Accounting Services Agreement (Association)', '一般社団法人への事務委託契約', '{"party_a": "spc", "party_b": "accounting_delegate"}', 9)
ON CONFLICT DO NOTHING;

-- 4. Add RLS policies for update/delete on deal_stakeholders
--    (SELECT and INSERT policies already exist from the initial migration)
CREATE POLICY "deal_stakeholders_delete" ON deal_stakeholders FOR DELETE USING (true);
