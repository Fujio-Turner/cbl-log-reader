# Couchbase Lite Log Reader

A tool that processes Couchbase Lite log files and inserts them into Couchbase Server for analysis. Includes a web dashboard for visualizing log activity, errors, and replication performance.

## The Problem

You have Couchbase Lite log files, but you need help understanding what they mean and identifying issues like replication errors or performance bottlenecks.

## What It Does

- **Parses** Couchbase Lite log files (`.txt`, `.log`, `.cbllog`)
- **Inserts** structured log data into a Couchbase bucket for powerful SQL++ and FTS queries
- **Generates** a `log_report` summary with timestamps, error counts, and replication stats
- **Dashboard** — a web UI for filtering, charting, and searching logs in real time

![Dashboard Screenshot](static/screenshot.png)

## Dashboard Features

### Charts (powered by Apache ECharts)
All charts are interactive with tooltips, legends, and zoom capabilities.

| Chart | Description |
|---|---|
| **Main Line Chart** | Log volume over time by type. Supports drag-to-zoom (draw a rectangle), slider zoom, linear/log scale toggle, and stake annotations. |
| **Pie Chart** | Distribution of log types (donut style with scrollable legend). |
| **Top Types** | Horizontal bar chart of the top 15 log types by count. |
| **Treemap** | Proportional area view of log type distribution. |
| **Stacked Bar** | Log volume stacked by type, aggregated by hour. |
| **Error Rate** | Dual-axis chart showing error rate %, total logs, and error count over time. Supports stake annotations. |
| **Heatmap** | Day × hour heatmap with color-coded log volume and interactive tooltips. |
| **Sync Timeline** | Horizontal bar chart of replication sessions showing duration, docs processed, and write rejections. |
| **Sync Gantt** | Gantt-style chart showing concurrent replication sessions per process ID on a time axis. Supports drag-to-zoom. |

### Filtering & Controls
- **Date Range** — Flatpickr date/time pickers with second-level precision
- **Log Type Filter** — Multi-select with Select All / Unselect All
- **Type Mode** — Toggle between General (e.g., `Sync`) and Specific (e.g., `Sync:Checkpoint`) grouping
- **Grouping** — Toggle between by-second and by-minute aggregation (auto-refreshes charts)
- **Scale Toggle** — Switch the main line chart Y-axis between linear and logarithmic scale
- **📅 Use Chart's X-Axis Values** — Copy the current zoomed range from the line chart into the date pickers
- **Search** — Full-text search with support for AND/OR/NOT operators, exact phrases (`"connection refused"`), field filters (`type:Sync`, `pid:1047`, `error:true`), prefix matching (`retry*`), and exclusions (`-healthcheck`)

### Stakes (Annotations)
Click the 📍 button on any row in the Raw Data table to place a vertical dashed line (stake) on the line chart and error rate chart at that log entry's timestamp. Stakes are color-coded and labeled with the row number. Use **Clear All Stakes** to remove them.

### Replication Tables
- **Replicator** — Lists replication starts with process IDs, endpoints, and collection counts
- **Document Process** — Shows docs processed and write rejections per replication session, with checkbox filters to hide zero-count rows

## Quick Start

### Option A: Docker (Recommended)

> **Prerequisite:** A running Couchbase Server 7.x with buckets and indexes set up (see [INSTALLATION.md](INSTALLATION.md#step-5-set-up-couchbase-server)).

1. Clone the repo and update `config.json` with your Couchbase credentials and log file path
2. Place your log files in the `cbl_logs/` folder
3. Run:

```bash
# Process logs into Couchbase
docker compose run cbl-log-reader python3 cbl_log_reader.py config.json

# Start the dashboard
docker compose up
```

Dashboard opens at **http://127.0.0.1:5099**

### Option B: Local Python

```bash
git clone https://github.com/fujio-turner/cbl-log-reader.git
cd cbl-log-reader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then follow the full setup in **[INSTALLATION.md](INSTALLATION.md)**.

## Converting Binary Logs

Couchbase Lite writes binary `.cbllog` files. You must convert them to text first using the **`cblite` CLI tool (version 2.x only)**.

> ⚠️ **Only cblite 2.x has the `logcat` command.** Versions 3.x removed it. Download **2.8.0** from:
> https://github.com/couchbaselabs/couchbase-mobile-tools/releases

```bash
./cblite logcat --out cbl-log-output.txt /path/to/cbllog-files/
```

If your logs are already plain text, skip this step.

## Configuration

Edit `config.json`:

```json
{
    "file-to-parse": "/path/to/cbl-log-output.txt",
    "file-parse-type": "info|error|debug|verbose|warning",
    "cb-cluster-host": "your-couchbase-host",
    "cb-bucket-name": "cbl-log-reader",
    "cb-bucket-user": "Administrator",
    "cb-bucket-user-password": "password",
    "cb-expire": 0,
    "debug": false
}
```

See [INSTALLATION.md](INSTALLATION.md#step-6-configure-configjson) for field details.

## Couchbase Server Requirements

You need two buckets and some indexes. See [INSTALLATION.md — Step 5](INSTALLATION.md#step-5-set-up-couchbase-server) for details:

- **Buckets:** `cbl-log-reader` + `cache`
- **SQL++ Indexes:** 5 indexes (listed in `cb_sql_indexes.txt`)
- **FTS Index:** Import `cb_fts_index.json` via the Couchbase Search UI

## Usage

```bash
# 1. Process logs
python3 cbl_log_reader.py config.json

# 2. Start dashboard
python3 app.py config.json
```

## Sample Queries

See [sample-sql-queries.md](sample-sql-queries.md) for useful SQL++ queries to run against your log data in the Couchbase Query Workbench.

## Troubleshooting

See [INSTALLATION.md — Troubleshooting](INSTALLATION.md#troubleshooting) for common issues:

- SDK build failures on Python 3.13+
- macOS permission errors
- Port conflicts
- Binary log conversion errors
- Dashboard showing no data

## License

See [LICENSE](LICENSE)
