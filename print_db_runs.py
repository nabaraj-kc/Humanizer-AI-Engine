import sqlite3
import sys

def print_runs():
    conn = sqlite3.connect('storage/humanizer.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    print("=== PAPER RUNS ===")
    c.execute("SELECT run_id, filename, status, start_time, total_chunks, master_summary FROM paper_runs ORDER BY start_time DESC LIMIT 10")
    runs = c.fetchall()
    for run in runs:
        print(f"Run ID: {run['run_id']}")
        print(f"  Filename: {run['filename']}")
        print(f"  Status: {run['status']}")
        print(f"  Start Time: {run['start_time']}")
        print(f"  Total Chunks: {run['total_chunks']}")
        summary = run['master_summary']
        summary_snippet = (summary[:150] + "...") if summary else "None"
        print(f"  Master Summary: {summary_snippet}")
        
        # Get chunks
        c.execute("SELECT sequence_no, iterations, raw_text, clean_text, processed FROM text_chunks WHERE run_id = ?", (run['run_id'],))
        chunks = c.fetchall()
        print(f"  Chunks ({len(chunks)}):")
        for chunk in chunks:
            raw = chunk['raw_text'] or ""
            proc = chunk['processed'] or ""
            equal = (raw == proc)
            print(f"    Chunk {chunk['sequence_no']}: iterations={chunk['iterations']}, len(raw)={len(raw)}, len(proc)={len(proc)}, raw==proc? {equal}")
            if len(raw) < 200:
                print(f"      Raw:  {raw}")
                print(f"      Proc: {proc}")
            else:
                print(f"      Raw Snippet:  {raw[:80]}...")
                print(f"      Proc Snippet: {proc[:80]}...")
        print("-" * 50)

if __name__ == "__main__":
    print_runs()
