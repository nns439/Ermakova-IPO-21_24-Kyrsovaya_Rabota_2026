PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS client_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tariffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    short_description TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    is_new INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES client_categories(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tariff_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tariff_id INTEGER NOT NULL UNIQUE,
    mobile_gb INTEGER NOT NULL DEFAULT 0,
    unlimited_mobile INTEGER NOT NULL DEFAULT 0,
    sms INTEGER NOT NULL DEFAULT 0,
    minutes INTEGER NOT NULL DEFAULT 0,
    home_internet_included INTEGER NOT NULL DEFAULT 0,
    home_speed_mbps INTEGER NOT NULL DEFAULT 0,
    tv_channels INTEGER NOT NULL DEFAULT 0,
    cinema_included INTEGER NOT NULL DEFAULT 0,
    parental_control INTEGER NOT NULL DEFAULT 0,
    spam_protection INTEGER NOT NULL DEFAULT 0,
    monthly_price INTEGER NOT NULL,
    FOREIGN KEY (tariff_id) REFERENCES tariffs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    monthly_price INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tariff_services (
    tariff_id INTEGER NOT NULL,
    service_id INTEGER NOT NULL,
    PRIMARY KEY (tariff_id, service_id),
    FOREIGN KEY (tariff_id) REFERENCES tariffs(id) ON DELETE CASCADE,
    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    weight REAL NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS selection_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tariff_id INTEGER NOT NULL,
    desired_price INTEGER NOT NULL,
    desired_gb INTEGER NOT NULL DEFAULT 0,
    need_unlimited INTEGER NOT NULL DEFAULT 0,
    desired_minutes INTEGER NOT NULL DEFAULT 0,
    desired_sms INTEGER NOT NULL DEFAULT 0,
    need_home_internet INTEGER NOT NULL DEFAULT 0,
    desired_home_speed INTEGER NOT NULL DEFAULT 0,
    preference_category_id INTEGER,
    score REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (tariff_id) REFERENCES tariffs(id) ON DELETE CASCADE,
    FOREIGN KEY (preference_category_id) REFERENCES client_categories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tariff_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (tariff_id) REFERENCES tariffs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS view_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tariff_id INTEGER NOT NULL,
    viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (tariff_id) REFERENCES tariffs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tariffs_category ON tariffs(category_id);
CREATE INDEX IF NOT EXISTS idx_tariffs_active ON tariffs(is_active);
CREATE INDEX IF NOT EXISTS idx_tariff_parameters_price ON tariff_parameters(monthly_price);
CREATE INDEX IF NOT EXISTS idx_selection_history_tariff ON selection_history(tariff_id);
CREATE INDEX IF NOT EXISTS idx_selection_history_created ON selection_history(created_at);
CREATE INDEX IF NOT EXISTS idx_view_history_user ON view_history(user_id, viewed_at);
CREATE INDEX IF NOT EXISTS idx_reviews_tariff ON reviews(tariff_id);
