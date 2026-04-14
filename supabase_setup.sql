CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    post_id TEXT UNIQUE NOT NULL,
    agent_name TEXT NOT NULL,
    agent_id TEXT,
    title TEXT,
    service_type TEXT,
    description TEXT,
    price REAL,
    currency TEXT,
    payment_method TEXT,
    endpoint_url TEXT,
    submolt TEXT,
    source_url TEXT,
    is_active BOOLEAN DEFAULT true,
    raw_content TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    post_created_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_services_type ON services(service_type);
CREATE INDEX IF NOT EXISTS idx_services_agent ON services(agent_name);
CREATE INDEX IF NOT EXISTS idx_services_price ON services(price);

ALTER TABLE services ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read access" ON services FOR SELECT USING (true);
CREATE POLICY "Service key write" ON services FOR ALL USING (true) WITH CHECK (true);
