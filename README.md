# Couchbase Lite Log Reader

## The Problem

You have the Couchbase Lite log files, but you need help understanding what they mean.

## This Project

This project will process the files and put them into a local Couchbase bucket to make more sense of them.

This projects will:

Aggregate , consolidate and process the logs. So you can do SQL++ & CB FTS on them enabling things like:
* `GROUP BY` 
* `ORDER BY`
* `BETWEEN TO AND FROM`
* `SEARCH(rawLog,"*pull*")`
* `MIN` , `MAX` and more.

Click on the links to learm more about [SQL++](https://docs.couchbase.com/server/current/n1ql/n1ql-language-reference/index.html) & [FTS](https://docs.couchbase.com/server/current/fts/fts-searching-from-N1QL.html#search) docs in Couchbase.




### Requirements
- Couchbase 7.x with Data, Query & Index (CE or EE)
- Python 3 (3.9.18 or later)
- Python Couchbase SDK - Download here: [Python Couchbase SDK](https://github.com/couchbase/couchbase-python-client)
- Couchbase Lite log files - Documentation on creating CBL logs: [Couchbase Lite Troubleshooting Logs](https://docs.couchbase.com/couchbase-lite/current/swift/troubleshooting-logs.html#lbl-file-logs)
- Couchbase Lite CLI Tool - Download here: [Couchbase Mobile Tools Releases](https://github.com/couchbaselabs/couchbase-mobile-tools/releases)

### Set Up
- Create a Couchbase bucket called: `cbl-log-reader`.`_default`.`_default`
- Create this index on the bucket:

```SQL
CREATE INDEX `cblDtRange_v5` ON `cbl-log-reader`.`_default`.`_default`(`dt`,`logLine`,`type`,`error`,`fileName`)
```

- Install [Couchbase Python SDK](https://docs.couchbase.com/python-sdk/current/hello-world/start-using-sdk.html#quick-installation) docs here.

- Download this repo in your Download folder 

- (Optional) Many time the CBL logs when parsed and added into the bucket can be millions of documents. If you then in your SQL++ query use the `AND SEARCH(rawLog,"*errors*")` function, it will take a long time to process. To speed this up, you can create a FTS index on the `rawLog` field. In this repo I have a `optional_fts_index.json` that you can import into Couchbase.

### Running

#### Consolidate The Log Files
When you get the cbl logs, you will have a bunch of logs in a folder called `cbllog` ,but you need to process/consolidated the files in to one big file.

Run the CBL CLI tool you downloaded from above like below to create this consolidated file.

```shell
/home/downloads/cbl/tools/cblite logcat --out cbl-log-big.txt /home/downloads/cbllog/
```

#### Update the config.json
In the Terminal, `cd` into the folder of the repository download location.

```shell
cd /home/dowloads/cbl-log-reader/ 
```

Open and update the `config.json` with your Couchbase user credintals and the path and name of the consolidated log file `cbl-log-big.txt`. Save the file.

#### Process and Insert the data from the file into Couchbase

The script below will run the script and insert the logs into the above bucket.

```shell
python3 cbl-log-reader.py config.json
```
#### Query Your Data
Log into the Couchbase Server to query the `cbl-log-reader` bucket.

In this repository, there are some helpful sample queries in the file [sample-sql-queries](sample-sql-queries.md) that you can use.


#### RELEASE NOTES

- Updated to work with new Couchbase Lite 3.2.x ISO-8601 Time Stamp format and log file format.