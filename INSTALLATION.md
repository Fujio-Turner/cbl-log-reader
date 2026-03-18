# CBL Log Reader — Installation & Setup Guide

A step-by-step guide to getting CBL Log Reader running on your machine.

---

## Prerequisites

- **Python 3.9+** (tested up to 3.14 — see note about SDK compatibility below)
- **Couchbase Server 7.x** running locally or on a remote host
- **Git**

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/fujio-turner/cbl-log-reader.git
cd cbl-log-reader
```

---

## Step 2: Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows
```

---

## Step 3: Install Dependencies

Install the Couchbase Python SDK:

```bash
pip install couchbase
```

> **⚠️ SDK Version Note:** The `requirements.txt` pins `couchbase==4.3.0`, but that specific version **does not build** on Python 3.13 or 3.14. Running `pip install couchbase` (without a version pin) will fetch the latest compatible release, which is recommended. Alternatively, use `pip install "couchbase>=4.3.0"`.

Install Flask (required by the dashboard but **not listed** in `requirements.txt`):

```bash
pip install flask
```

---

## Step 4: Get the Couchbase Lite CLI Tool (`cblite`)

Couchbase Lite writes binary `.cbllog` files. To use them with CBL Log Reader, you must first convert them to plain text using the `cblite logcat` command.

> **🚨 IMPORTANT:** Only **cblite 2.x** has the `logcat` subcommand. Versions 3.x **removed it entirely**. You must download a 2.x release.

### Download cblite 2.8.x

Go to the releases page and download the **2.8.0** (or latest 2.8.x) build for your platform:

👉 **https://github.com/couchbaselabs/couchbase-mobile-tools/releases**

Look for assets named like:
- `cblite-macos-2.8.0.zip` (macOS)
- `cblite-linux-2.8.0.zip` (Linux)
- `cblite-windows-2.8.0.zip` (Windows)

### Convert Binary Logs to Text

```bash
./cblite logcat --out cbl-log-output.txt /path/to/cbllog-files/
```

This reads all `.cbllog` files in the directory and produces a single consolidated text file.

> **Note:** If your log files are already plain text (`.txt` or `.log`), skip this step entirely.

---

## Step 5: Set Up Couchbase Server

### 5a. Create Buckets

You need **two** buckets in Couchbase Server:

| Bucket Name       | Purpose                                    |
|-------------------|--------------------------------------------|
| `cbl-log-reader`  | Stores parsed log data and the report doc  |
| `cache`           | Stores cached query results for the dashboard |

Create both via the Couchbase UI (**Buckets → Add Bucket**) or CLI.

### 5b. Create SQL++ (N1QL) Indexes

Run the following index creation statements in the Couchbase **Query Workbench** (or via `cbq`):

```sql
CREATE INDEX `big_hug_v2` ON `cbl-log-reader`(
  (all (`processId`)), `type`, `dt`, `processId`,
  ifmissingornull((`syncCommitStats`.`numInserts`), 0),
  ifmissingornull((`replicatorStatus`.`docs`), 0)
) WHERE ((split(`type`, ":")[0]) = "Sync");

CREATE INDEX `error_type_dt_v1` ON `cbl-log-reader`(`error`, `type`, `dt`);

CREATE INDEX `dt_v1` ON `cbl-log-reader`(`dt`);

CREATE INDEX `long_time_v2` ON `cbl-log-reader`(
  replace(substr0(`dt`, 0, 19), "T", " "),
  (split(`type`, ":")[0]), `type`, `dt`
);

CREATE INDEX `type_dt_v1` ON `cbl-log-reader`(`type`, `dt`);
```

### 5c. Import the Full-Text Search (FTS) Index

The dashboard requires an FTS index named **`cbl_rawLog_v3`** on the `cbl-log-reader` bucket.

1. Open the Couchbase UI → **Search** (under the *Search* tab)
2. Click **Add Index**
3. Click **Import** (or the import icon)
4. Paste the contents of `cb_fts_index.json` from this repository
5. Click **Create Index**

> Without this FTS index, the dashboard's search, chart, and pie-chart features will not work.

---

## Step 6: Configure `config.json`

Edit `config.json` in the project root:

```json
{
    "file-to-parse": "/path/to/your/cbl-log-output.txt",
    "file-parse-type": "info|error|debug|verbose|warning",
    "cb-cluster-host": "127.0.0.1",
    "cb-bucket-name": "cbl-log-reader",
    "cb-bucket-user": "Administrator",
    "cb-bucket-user-password": "your-password",
    "auto-start-dashboard": false,
    "cb-expire": 0,
    "debug": false
}
```

### Field Reference

| Field                      | Description                                                                                                  |
|----------------------------|--------------------------------------------------------------------------------------------------------------|
| `file-to-parse`            | Path to a single log file **or** a directory containing log files.                                           |
| `file-parse-type`          | Pipe-separated list of log types to process. Options: `info`, `error`, `debug`, `verbose`, `warning`. Use `info\|error\|debug\|verbose\|warning` for all. |
| `cb-cluster-host`          | Hostname or IP of your Couchbase Server.                                                                     |
| `cb-bucket-name`           | Target bucket name (should be `cbl-log-reader`).                                                             |
| `cb-bucket-user`           | Couchbase username with read/write access.                                                                   |
| `cb-bucket-user-password`  | Password for the Couchbase user.                                                                             |
| `auto-start-dashboard`     | Set to `true` to automatically launch the web dashboard after log processing.                                |
| `cb-expire`                | Document TTL in seconds. `0` means documents never expire.                                                   |
| `debug`                    | Set to `true` for verbose console output.                                                                    |

### How `file-to-parse` Works

- **Single file** (e.g., `/path/to/cbl-log-output.txt`): The file is processed directly. It must have a `.txt`, `.log`, or `.cbllog` extension.
- **Directory** (e.g., `/path/to/log-folder/`): The tool scans for files with `.txt`, `.log`, or `.cbllog` extensions **whose filenames contain** one of the types listed in `file-parse-type`. For example, with `file-parse-type` set to `info|error`, a file named `cbl_info_1.txt` matches but `cbl_verbose_1.txt` does not.

---

## Step 7: Process Log Files

```bash
python3 cbl_log_reader.py config.json
```

This parses the log file(s), extracts structured data, upserts documents into Couchbase, and generates a summary report document (`log_report`).

---

## Step 8: Launch the Dashboard

```bash
python3 app.py config.json
```

The dashboard will be available at:

👉 **http://127.0.0.1:5099**

> **macOS Note:** Port 5000 is commonly used by **AirPlay Receiver**. This app uses port **5099** to avoid that conflict.

Alternatively, set `"auto-start-dashboard": true` in `config.json` to have the dashboard launch automatically after log processing completes.

---

## Troubleshooting

### Couchbase SDK Build Failure

```
ERROR: Failed building wheel for couchbase
```

The pinned version `couchbase==4.3.0` may not compile on newer Python versions (3.13+). Install the latest version instead:

```bash
pip install couchbase
```

### PermissionError on macOS

```
PermissionError: [Errno 1] Operation not permitted: '/Users/.../Downloads/...'
```

macOS restricts access to `~/Downloads`, `~/Desktop`, and `~/Documents` for terminal applications. Either:
- Grant **Full Disk Access** to your Terminal app (System Settings → Privacy & Security → Full Disk Access)
- Or copy the log files to a non-restricted location (e.g., your home directory or the project folder)

### Port Already in Use

```
OSError: [Errno 48] Address already in use
```

Another process is using port 5099. You can change the port by editing the `web_port` variable at the top of `app.py`:

```python
web_port = 5099  # Change to an available port
```

### "No matching files found"

```
No matching .txt, .log, or .cbllog files found in /path/to/dir with types info|error
```

When `file-to-parse` points to a directory, files must:
1. Have a `.txt`, `.log`, or `.cbllog` extension
2. Contain the type name (e.g., `info`, `error`) somewhere in their filename

If your logs are in a single consolidated file, point `file-to-parse` directly to that file instead of the directory.

### UnicodeDecodeError When Processing Logs

```
UnicodeDecodeError: 'utf-8' codec can't decode byte ...
```

You are likely trying to process **binary** `.cbllog` files directly. Convert them to text first using `cblite logcat` (see [Step 4](#step-4-get-the-couchbase-lite-cli-tool-cblite)).

### Dashboard Shows No Data

- Verify log processing completed successfully (Step 7)
- Confirm the FTS index `cbl_rawLog_v3` exists and is built (Step 5c)
- Confirm the `cache` bucket exists (Step 5a)
- Check that `config.json` credentials and bucket name are correct
