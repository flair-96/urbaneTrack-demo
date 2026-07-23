import sqlite3

DATABASE_PATH = "urbaneTrack.db"

conn = sqlite3.connect(DATABASE_PATH)
cursor = conn.cursor()

cursor.execute("ALTER TABLE progress_notes ADD COLUMN goal_score INTEGER DEFAULT 0")
cursor.execute("ALTER TABLE progress_notes ADD COLUMN attendance_rate INTEGER DEFAULT 0")
cursor.execute("ALTER TABLE progress_notes ADD COLUMN therapist_rating INTEGER DEFAULT 0")
cursor.execute("ALTER TABLE progress_notes ADD COLUMN progress_status TEXT")
cursor.execute("ALTER TABLE progress_notes ADD COLUMN ai_recommendation TEXT")

conn.commit()
conn.close()

print("Columns added successfully!")