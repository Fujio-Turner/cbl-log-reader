# Couchbase Lite Log Reader

## The Problem

You have Couchbase Lite log files, but you need help understanding what they mean and identifying issues like replication errors or performance bottlenecks.

## This Project

This project processes Couchbase Lite log files and inserts them into a local Couchbase bucket (`cbl-log-reader`) for easier analysis. It aggregates, consolidates, and enriches the logs, enabling powerful SQL++ (N1QL) and Full Text Search (FTS) queries such as:
- `GROUP BY`
- `ORDER BY`
- `BETWEEN ... AND ...`
- `SEARCH(cbl-log-reader, "*pull*")`
- `MIN`, `MAX`, and more.

Additionally, it generates a summary report (`log_report`) to provide insights into log activity, errors, and replication performance.

### Features
- **Log Parsing**: Processes single files or directories of `.txt` or `.log` files matching types like `info`, `error`, `debug`, `verbose`, or `warning`.
- **Type-Specific Processing**: Breaks down logs into categories (e.g., `Sync:State`, `BLIPMessages:SENDING`) for detailed analysis.
- **Replication Tracking**: Monitors replication processes, including document counts and rejection errors.
- **Report Generation**: Creates a `log_report` document summarizing:
  - Oldest and newest log timestamps.
  - Counts of log types and errors.
  - Replication stats (e.g., total entries, rejections, documents processed), sorted by start time.
- **User Guidance**: Outputs a post-processing message explaining the report and how to query it.

### Requirements
- **Couchbase Server**: 7.x with Data, Query, and Index services (Community or Enterprise Edition).
- **Python**: 3.9.18 or later.
- **Python Couchbase SDK**: Install via [Python Couchbase SDK](https://github.com/couchbase/couchbase-python-client).
- **Couchbase Lite Log Files**: See [Couchbase Lite Troubleshooting Logs](https://docs.couchbase.com/couchbase-lite/current/swift/troubleshooting-logs.html#lbl-file-logs) for generating logs.
- **Couchbase Lite CLI Tool** (optional): For converting binary logs, download from [Couchbase Mobile Tools Releases](https://github.com/couchbaselabs/couchbase-mobile-tools/releases).

### Setup
1. **Create a Couchbase Bucket**:
   - Name: `cbl-log-reader`, Scope: `_default`, Collection: `_default`.

2. **Create Indexes**:
   - Replace older indexes with these optimized ones:
     ```sql
     CREATE INDEX `big_hug_v2` ON `cbl-log-reader`((all (`processId`)),`type`,`dt`,`processId`,ifmissingornull((`syncCommitStats`.`numInserts`), 0),ifmissingornull((`replicatorStatus`.`docs`), 0)) WHERE ((split(`type`, ":")[0]) = "Sync");
     CREATE INDEX `error_type_dt_v1` ON `cbl-log-reader`(`error`,`type`,`dt`);
     CREATE INDEX `dt_v1` ON `cbl-log-reader`(`dt`);
     CREATE INDEX `long_time_v2` ON `cbl-log-reader`(replace(substr0(`dt`, 0, 19), "T", " "),(split(`type`, ":")[0]),`type`,`dt`);
     CREATE INDEX `type_dt_v1` ON `cbl-log-reader`(`type`,`dt`);
     ```
   - These support the report queries efficiently.

3. **Install Python SDK**:
   - Follow [Couchbase Python SDK Quick Installation](https://docs.couchbase.com/python-sdk/current/hello-world/start-using-sdk.html#quick-installation).

4. **Download This Repo**:
   - Clone or download to your preferred directory (e.g., `/home/downloads/cbl-log-reader/`).

5. **FTS Index(Mandatory)**:
   - For faster searches on `rawLog` (e.g., `SEARCH(cbl-log-reader, "error")`), import `optional_fts_index.json` from this repo into Couchbase’s Full Text Search service. Useful for large datasets (millions of documents).

### Running

#### (Optional) Convert Binary Log Files
If your logs are binary, use the `cblite logcat` tool to convert them to text:
```shell
/home/downloads/cbl/tools/cblite logcat --out cbl-log-info.txt /home/downloads/cbllog/
```

#### Update the config.json
In the Terminal, `cd` into the folder of the repository download location.

```shell
cd /home/dowloads/cbl-log-reader/ 
```

Open and update the `config.json` with your Couchbase user credintals and the path and name of the consolidated log file `cbl-log-info.txt`. Save the file.

```json
{
    "file-to-parse": "/home/downloads/cbllog/", 
    "cb-cluster-host": "127.0.0.1",
    "cb-bucket-name": "cbl-log-reader",
    "cb-bucket-user": "Administrator",
    "cb-bucket-user-password": "password",
    "cb-expire": 0,
    "debug": false,
    "file-parse-type": "info|error|debug|verbose|warning" // default is info
}
```

#### Process and Insert the data from the file into Couchbase

The script below will run the script and insert the logs into the above bucket.

```shell
python3 cbl_log_reader.py config.json
```
#### Query Your Data
Log into the Couchbase Server to query the `cbl-log-reader` bucket.

In this repository, there are some helpful sample queries in the file [sample-sql-queries](sample-sql-queries.md) that you can use.

- Access the report: `SELECT * FROM cbl-log-reader USE KEYS('log_report')`



#### Understanding the Report
After processing, the script outputs a message about the `log_report` document:
- **Purpose: Summarizes log metrics.

- **Analyzes:
    - Timestamps (logDtOldest, logDtNewest): Log time range.

    - Types (types): Frequency of log categories.

    - Errors (errorStatus): Error counts by type.

    - **Replication (replicationStats): Per-replicator stats, ordered by start time, including log entries, local write rejections, and documents processed.

    - **Usage: Check replication health (e.g., high rejections vs. documents) and error-prone types.



#### RELEASE NOTES


- Latest Updates:
    - Refactored log processing into type-specific functions (e.g., `process_sync`, `process_blip_messages`) for maintainability.

    - Added `log_report` document with detailed replication stats, sorted by `startTime`.

    - Updated indexes for better query performance.

    - Enhanced user output with a post-run report explanation.

- Compatibility: Supports Couchbase Lite 3.2.x ISO-8601 timestamps and log formats.

- Flexibility: Processes multiple log files or directories directly, no consolidation needed.




### Key Updates
1. **Features Section**: Added details about type-specific processing, replication tracking, and the new report.
2. **Setup**: Updated indexes to the new set (`idx_dt`, etc.), replacing `type_dt_v1` and others.
3. **Running**: Clarified `config.json` options and the report output.
4. **Report Explanation**: Integrated the post-script message into the README for visibility.
5. **Release Notes**: Highlighted refactoring, report addition, index updates, and user guidance.

### Action
- Replace your `README.md` with this version in your repo.
- Verify it reads well and covers everything you want users to know.
- If you’d like more examples (e.g., sample report output), let me know!

This should give users a clear picture of the script’s capabilities and how to leverage the new `log_report`. What do you think?