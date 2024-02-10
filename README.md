# Couchbase Lite Log Reader
 
## THE PROBLEM

You got the Couchbase Lite Log files , but you want some help into what they mean.


## THIS PROJECT

The project will process the files and put them into a local couchbase bucket to make some more sense of them.


### Required
- Couchbase 7.x with Data , Query & Index (CE or EE)

- Python 3 (3.9.18 or better)

- Couchbase Lite log files - Docs on creating CBL logs DOCS: https://docs.couchbase.com/couchbase-lite/current/swift/troubleshooting-logs.html#lbl-file-logs

- Couchbase lite CLI Tool - Download here: https://github.com/couchbaselabs/couchbase-mobile-tools/releases


### SET UP 
- Create Couchbase bucket called: `cbl-log-reader`.`_default`.`_default`

- Create an index on the bucket: 

```SQL
CREATE INDEX `cblDtRange_v5` ON `cbl-log-reader`.`_default`.`_default`(`dt`,`logLine`,`type`,`error`,`fileName`)
```

- Install Couchbase Python SDK - Docs here: https://docs.couchbase.com/python-sdk/current/hello-world/start-using-sdk.html#quick-installation

- Download this repo in your Download folder 

### RUNNING

#### Consolidate The Log Files
When you get the cbl logs you will have a bunch of logs in a folder called `cbllog` but you need to process /consolidated the files in to one big file.

Run the CBL CLI tool you download from above like below to create this consolidated file.

```shell
/home/downloads/cbl/tools/cblite logcat --out cbl-log-big.txt /home/downloads/cbllog/
```

#### Update the config.json
In the Terminal `cd` into the folder of the repo download location.

```shell
cd /home/dowloads/cbl-log-reader/ 
```

Open and update the `config.json` with your couchbase user credintals and path and name of the consolidated log file `cbl-log-big.txt`. Save the file.

#### Process and Insert the data from the file into Couchbase

The script below will run the script and insert the logs into the above bucket.

```shell
python3 cbl-log-reader.py config.json
```
#### Query Your Data
Log into the Couchbase Server to query the `cbl-log-reader` bucket.

In this repo there are some helpful sample queries in the file [sample-sql-queries](sample-sql-queries.md) that you can use.