-- 1. Limpieza (Borrar todo lo anterior para empezar limpio)
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS account_types CASCADE;
DROP TABLE IF EXISTS currencies CASCADE;
DROP TABLE IF EXISTS import_sources CASCADE;

-- 2. Tablas Maestras
CREATE TABLE currencies (
    currency_code CHAR(3) PRIMARY KEY,
    currency_name VARCHAR(50),
    symbol VARCHAR(5)
);

CREATE TABLE account_types (
    type_id SERIAL PRIMARY KEY,
    type_name VARCHAR(50) NOT NULL UNIQUE, -- 'Bank', 'Cash', 'Credit Card'
    classification VARCHAR(20) NOT NULL CHECK (classification IN ('ASSET', 'LIABILITY'))
);

-- Usuarios base (para vincular presupuestos)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    role TEXT DEFAULT 'user',
    profile_status TEXT DEFAULT 'incomplete',
    financial_goals TEXT,
    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Tablas Principales
CREATE TABLE accounts (
    account_id SERIAL PRIMARY KEY,
    account_name VARCHAR(100) NOT NULL UNIQUE,
    account_type_id INT REFERENCES account_types(type_id),
    currency_code CHAR(3) REFERENCES currencies(currency_code) DEFAULT 'COP',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Categorías maestras para presupuesto
CREATE TABLE IF NOT EXISTS master_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('fixed', 'variable', 'savings'))
);

-- Presupuestos mensuales por categoría y usuario
CREATE TABLE IF NOT EXISTS monthly_budgets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES master_categories(id),
    month DATE NOT NULL,
    amount_limit DECIMAL(15,2) NOT NULL DEFAULT 0,
    UNIQUE(user_id, category_id, month)
);

CREATE TABLE transactions (
    transaction_id SERIAL PRIMARY KEY,
    account_id INT REFERENCES accounts(account_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    amount NUMERIC(19, 4) NOT NULL, -- Soporta cifras grandes y decimales
    description TEXT,
    category VARCHAR(100), -- Por ahora texto simple, luego normalizaremos
    category_id INTEGER REFERENCES master_categories(id),
    status VARCHAR(20) DEFAULT 'CLEARED',
    import_source VARCHAR(255), -- Nombre del archivo CSV
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Datos Semilla (Seed Data) - Lo mínimo para que funcione
INSERT INTO currencies (currency_code, currency_name, symbol) VALUES 
('COP', 'Peso Colombiano', '$'),
('USD', 'Dólar Americano', '$');

INSERT INTO account_types (type_name, classification) VALUES 
('Bank Account', 'ASSET'),
('Cash', 'ASSET'),
('Credit Card', 'LIABILITY'),
('Investment', 'ASSET'),
('Wallet', 'ASSET');
