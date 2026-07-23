import sqlite3

DATABASE_PATH = "urbaneTrack.db"

conn = sqlite3.connect(DATABASE_PATH)

columns = conn.execute(
    "PRAGMA table_info(progress_notes)"
).fetchall()

for column in columns:
    print(column)

conn.close()