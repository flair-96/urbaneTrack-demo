import sqlite3

conn = sqlite3.connect("urbaneTrack.db")
cursor = conn.cursor()

# Check all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables:")
print(cursor.fetchall())

print("\nAppointments:")

cursor.execute("SELECT * FROM appointments")
rows = cursor.fetchall()

print("Number of appointments:", len(rows))

for row in rows:
    print(row)

conn.close()