import sqlite3
c = sqlite3.connect("loom.db")
print(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usage_limits'").fetchall())
