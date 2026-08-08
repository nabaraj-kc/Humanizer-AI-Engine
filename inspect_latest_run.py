import sqlite3

def inspect_latest_run():
    conn = sqlite3.connect('storage/humanizer.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT raw_text, clean_text, processed, iterations FROM text_chunks WHERE run_id='c79c6ead-6de2-40b8-813b-9baa22f68824'")
    row = c.fetchone()
    if row:
        raw = row['raw_text']
        clean = row['clean_text']
        proc = row['processed']
        print(f"Iterations: {row['iterations']}")
        print(f"Raw len: {len(raw)}, Clean len: {len(clean)}, Proc len: {len(proc)}")
        print(f"Raw == Proc? {raw == proc}")
        print(f"Clean == Proc? {clean == proc}")
        print("\n--- RAW TEXT ---")
        print(repr(raw))
        print("\n--- PROCESSED TEXT ---")
        print(repr(proc))
    else:
        print("Not found")

if __name__ == "__main__":
    inspect_latest_run()
