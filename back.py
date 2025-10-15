import psycopg2
import csv
from datetime import datetime

conn = psycopg2.connect(
    dbname="railway",
    user="postgres",
    password="WXcMHqMZHYPUHlhowqNLiOzFJytThxNB",
    host="junction.proxy.rlwy.net",
    port="14504"
)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup_file = f"railway_backup_{timestamp}.csv"

cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
tables = [t[0] for t in cur.fetchall()]

with open(backup_file, "w", newline='', encoding="utf-8") as f:
    writer = csv.writer(f)
    for table in tables:
        cur.execute(f"SELECT * FROM {table};")
        rows = cur.fetchall()
        writer.writerow([f"Table: {table}"])
        writer.writerows(rows)
        writer.writerow([])

cur.close()
conn.close()

print(f"✅ Backup completed → {backup_file}")
