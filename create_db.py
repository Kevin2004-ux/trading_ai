# create_db.py
import sqlite3

# Connect to (or create) the database file
conn = sqlite3.connect('strategy_library.db')
cursor = conn.cursor()

print("Creating 'strategies' table...")
# Create a table to store the best parameters for each regime
cursor.execute('''
    CREATE TABLE IF NOT EXISTS strategies (
        regime_id INTEGER PRIMARY KEY,
        profit_target REAL,
        stop_loss REAL,
        win_rate REAL,
        backtest_return REAL,
        last_updated TEXT
    )
''')

conn.commit()
conn.close()
print("Database and table created successfully.")