import sqlite3

conn = sqlite3.connect('storage/humanizer.db')
c = conn.cursor()
c.execute("SELECT raw_text, clean_text, processed FROM text_chunks WHERE run_id='c79c6ead-6de2-40b8-813b-9baa22f68824'")
row = c.fetchone()
if row:
    print(f"RAW length: {len(row[0])}")
    print(f"CLEAN length: {len(row[1])}")
    print(f"PROCESSED length: {len(row[2])}")
    print(f"RAW == PROCESSED? {row[0] == row[2]}")
else:
    print("Not found")
