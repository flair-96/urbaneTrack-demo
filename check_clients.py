import sqlite3

conn = sqlite3.connect("urbaneTrack.db")

rows = conn.execute("""
    SELECT *
    FROM clients
""").fetchall()

print("Number of clients:", len(rows))

for row in rows:
    print(row)

conn.close()