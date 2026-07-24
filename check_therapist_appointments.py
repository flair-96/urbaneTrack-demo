import sqlite3

conn = sqlite3.connect("urbaneTrack.db")

rows = conn.execute("""
SELECT
    appointment_id,
    therapist_user_id,
    appointment_type,
    confirmation_status,
    client_id
FROM appointments
ORDER BY appointment_id
""").fetchall()

print("Appointments:")
for row in rows:
    print(row)

conn.close()