import pathlib, datetime, pandas as pd, matplotlib, psycopg2, boto3, json, os
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / '.env')

DOWNLOADS_DIR = pathlib.Path('/mnt/c/Users/juana/Downloads').resolve()
REPORT_DIR = pathlib.Path('/home/juana/miami-analysis/reports')
REPORT_DIR.mkdir(exist_ok=True)

DB = dict(dbname='downloads_audit', user='juana', password=os.getenv('DB_PASSWORD'), host='localhost')
SNS_ARN = os.getenv('SNS_ARN')
LOG_GROUP = '/downloads-audit'
LOG_STREAM = f"run-{datetime.date.today()}"

sns = boto3.client('sns', region_name='us-east-2')
logs = boto3.client('logs', region_name='us-east-2')

def safe_path(p):
    try:
        p.resolve().relative_to(DOWNLOADS_DIR)
        return True
    except ValueError:
        return False

def init_db(cur):
    cur.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            scan_date DATE NOT NULL,
            total_files INT,
            total_size_mb FLOAT,
            files_over_1gb INT,
            files_over_365_days INT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            scan_date DATE NOT NULL,
            filename TEXT,
            extension TEXT,
            size_mb FLOAT,
            date_modified DATE,
            age_days INT
        )
    ''')

def log_to_cloudwatch(message: dict):
    try:
        logs.create_log_stream(logGroupName=LOG_GROUP, logStreamName=LOG_STREAM)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_log_events(
        logGroupName=LOG_GROUP,
        logStreamName=LOG_STREAM,
        logEvents=[{
            'timestamp': int(datetime.datetime.now().timestamp() * 1000),
            'message': json.dumps(message)
        }]
    )

TODAY = datetime.date.today()
records = []
for entry in DOWNLOADS_DIR.iterdir():
    if not safe_path(entry) or not entry.is_file():
        continue
    try:
        stat = entry.stat()
    except (PermissionError, OSError):
        continue
    ext = entry.suffix.lower() if entry.suffix else '(no ext)'
    size_mb = stat.st_size / (1024**2)
    modified = datetime.date.fromtimestamp(stat.st_mtime)
    records.append({'filename': entry.name, 'extension': ext,
                    'size_mb': round(size_mb, 3), 'date_modified': modified,
                    'age_days': (TODAY - modified).days})

df = pd.DataFrame(records)

conn = psycopg2.connect(**DB)
cur = conn.cursor()
init_db(cur)

cur.execute('''
    INSERT INTO scans (scan_date, total_files, total_size_mb, files_over_1gb, files_over_365_days)
    VALUES (%s, %s, %s, %s, %s)
''', (TODAY, int(len(df)), float(round(df['size_mb'].sum(), 2)),
      int(len(df[df['size_mb'] >= 1024])),
      int(len(df[df['age_days'] >= 365]))))

for _, row in df.iterrows():
    cur.execute('''
        INSERT INTO files (scan_date, filename, extension, size_mb, date_modified, age_days)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (TODAY, row['filename'], row['extension'], float(row['size_mb']),
          row['date_modified'], int(row['age_days'])))

conn.commit()
cur.close()
conn.close()
print('Logged to PostgreSQL.')

oversized = df[df['size_mb'] >= 1024]
ancient = df[df['age_days'] >= 365]
is_monthly = TODAY.day == 1

notable_lines = []
if not oversized.empty:
    for _, r in oversized.iterrows():
        notable_lines.append(f"  {r['size_mb']/1024:.2f} GB  |  {r['filename']}")
if not ancient.empty:
    for _, r in ancient.iterrows():
        notable_lines.append(f"  {r['age_days']} days old  |  {r['filename']}")

if notable_lines or is_monthly:
    subject = f"Downloads Audit — {TODAY}"
    body = f"Downloads Audit Report — {TODAY}\n"
    body += f"Total files: {len(df)}\n"
    body += f"Total size: {df['size_mb'].sum()/1024:.2f} GB\n\n"
    if notable_lines:
        body += "NOTABLE FILES:\n"
        body += "\n".join(notable_lines)
    else:
        body += "No notable files today."
    sns.publish(TopicArn=SNS_ARN, Subject=subject, Message=body)
    print('Alert sent.')
else:
    print('No notable files. No alert sent.')

log_to_cloudwatch({
    'date': str(TODAY),
    'total_files': int(len(df)),
    'total_size_gb': round(float(df['size_mb'].sum()) / 1024, 2),
    'files_over_1gb': int(len(oversized)),
    'files_over_365_days': int(len(ancient)),
    'alert_sent': bool(notable_lines or is_monthly)
})
print('Logged to CloudWatch.')

ext_counts = df['extension'].value_counts()
threshold = max(1, int(len(df) * 0.02))
small_exts = ext_counts[ext_counts <= threshold].index
pie_series = ext_counts.copy()
pie_series['other'] = pie_series[small_exts].sum()
pie_series = pie_series.drop(index=small_exts).sort_values(ascending=False)
top_size = df.nlargest(15, 'size_mb')

fig = plt.figure(figsize=(16, 12))
fig.suptitle(f'Downloads Audit — {TODAY}', fontsize=18, fontweight='bold')
gs = GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

ax_pie = fig.add_subplot(gs[0, 0])
ax_pie.pie(pie_series.values, labels=pie_series.index, autopct='%1.1f%%',
           startangle=140, colors=plt.cm.Set3.colors[:len(pie_series)])
ax_pie.set_title('File Types by Count', fontweight='bold')

ax_bar = fig.add_subplot(gs[0, 1])
short_names = [n if len(n)<=28 else n[:25]+'...' for n in top_size['filename']]
ax_bar.barh(short_names[::-1], top_size['size_mb'].values[::-1], color='steelblue')
ax_bar.set_xlabel('Size (MB)')
ax_bar.set_title('Top 15 Files by Size', fontweight='bold')
ax_bar.tick_params(axis='y', labelsize=7)

ax_old = fig.add_subplot(gs[1, 0])
ax_old.axis('off')
oldest = df.nlargest(10, 'age_days')[['filename','age_days','date_modified']].copy()
oldest['filename'] = oldest['filename'].apply(lambda n: n if len(n)<=30 else n[:27]+'...')
oldest['date_modified'] = oldest['date_modified'].astype(str)
tbl = ax_old.table(cellText=oldest.values, colLabels=['Filename','Age (days)','Modified'],
                   cellLoc='left', loc='center')
tbl.auto_set_font_size(False)
tbl.set_fontsize(7.5)
tbl.auto_set_column_width([0,1,2])
ax_old.set_title('10 Oldest Files', fontweight='bold', pad=12)

ax_big = fig.add_subplot(gs[1, 1])
ax_big.axis('off')
biggest = df.nlargest(10, 'size_mb')[['filename','size_mb']].copy()
biggest['filename'] = biggest['filename'].apply(lambda n: n if len(n)<=30 else n[:27]+'...')
biggest['size_mb'] = biggest['size_mb'].apply(lambda v: f'{v/1024:.2f} GB' if v>=1024 else f'{v:.1f} MB')
tbl2 = ax_big.table(cellText=biggest.values, colLabels=['Filename','Size'],
                    cellLoc='left', loc='center')
tbl2.auto_set_font_size(False)
tbl2.set_fontsize(7.5)
tbl2.auto_set_column_width([0,1])
ax_big.set_title('10 Biggest Files', fontweight='bold', pad=12)

report_path = REPORT_DIR / f'report_{TODAY}.png'
plt.savefig(report_path, dpi=150, bbox_inches='tight')
plt.close()
print(f'Report saved: {report_path}')
