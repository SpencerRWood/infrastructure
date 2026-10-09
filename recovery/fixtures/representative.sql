-- Synthetic representative backup; no live service data or credentials.
CREATE TABLE recovery_fixture (
    id integer PRIMARY KEY,
    label text NOT NULL UNIQUE,
    amount integer NOT NULL CHECK (amount > 0)
);
INSERT INTO recovery_fixture VALUES
    (1, 'alpha', 10), (2, 'beta', 20), (3, 'gamma', 30);
