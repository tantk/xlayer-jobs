ALTER TABLE services ADD COLUMN IF NOT EXISTS wallet_address TEXT;
ALTER TABLE services ADD COLUMN IF NOT EXISTS tx_count INTEGER;
ALTER TABLE services ADD COLUMN IF NOT EXISTS total_value_usd REAL;
ALTER TABLE services ADD COLUMN IF NOT EXISTS last_chain_check TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_services_wallet ON services(wallet_address);
