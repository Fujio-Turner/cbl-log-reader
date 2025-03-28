
----------------------------------------------------------------------------------------------------------

### Create this index to `cbl-log-reader` bucket with below queries

----------------------------------------------------------------------------------------------------------
```SQL
CREATE INDEX type_dt_v1 ON `cbl-log-reader` (`type`, `dt`);
CREATE INDEX error_type_dt_v1 ON `cbl-log-reader` (`error`, `type`, `dt`);
CREATE INDEX rep_dt_type_v1 ON `cbl-log-reader` (`replicationId`, `dt`, `type`);
```


----------------------------------------------------------------------------------------------------------

### Get a Count and names of all the Log line types , and error of those types too.

#### Examples: "DB","Sync","SQL","Query","WS","Blip"

----------------------------------------------------------------------------------------------------------
```SQL
SELECT COUNT(`type`) AS cType ,
       `type` ,
       `error`
FROM `cbl-log-reader`
WHERE `dt` IS NOT MISSING
    AND `type` IS NOT MISSING
GROUP BY `type`,
         `error`
ORDER BY cType DESC
```


----------------------------------------------------------------------------------------------------------

### Get counts & errors of all the Log lines. This will show you how many of a particular error type there are.

----------------------------------------------------------------------------------------------------------

```SQL
SELECT COUNT(errorType) AS cError,
       errorType
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` IS NOT MISSING
    AND logLine IS NOT MISSING
    AND error IS NOT MISSING
GROUP BY errorType
ORDER BY cError DESC
```

----------------------------------------------------------------------------------------------------------

### See all the logs with Errors.

----------------------------------------------------------------------------------------------------------

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` IS NOT NULL
    AND `error` = True
ORDER BY dt
LIMIT 1000
OFFSET 0
```


----------------------------------------------------------------------------------------------------------

### See all the logs by a type.

#### "DB","Sync","SQL","Query","WS","Blip"

----------------------------------------------------------------------------------------------------------

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` = "Query"
    AND logLine IS NOT MISSING
ORDER BY dt
LIMIT 1000
OFFSET 0
```


----------------------------------------------------------------------------------------------------------

### See all the logs by multiple types.

#### "DB","Sync","SQL","Query","WS","Blip"

----------------------------------------------------------------------------------------------------------

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` IN ["Query","Sync"]
    AND logLine IS NOT MISSING
ORDER BY dt
LIMIT 1000
OFFSET 0
```


----------------------------------------------------------------------------------------------------------

### FTS the `rawLog`.

#### DOCS on FTS AND SQL++ here: https://docs.couchbase.com/server/current/fts/fts-searching-from-N1QL.html

----------------------------------------------------------------------------------------------------------

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` IS NOT MISSING
    AND logLine IS NOT MISSING
    AND SEARCH(rawLog, "*save*")
ORDER BY dt
LIMIT 1000
OFFSET 0
```


> [!WARNING]  
> FTS in all fields in the bucket(Warning Can be slow)


```SQL
SELECT clr.*
FROM `cbl-log-reader` as clr
WHERE clr.dt IS NOT MISSING
    AND clr.`type` IS NOT MISSING
    AND clr.logLine IS NOT MISSING
    AND SEARCH(clr, "*save*")
ORDER BY clr.dt
LIMIT 1000
OFFSET 0
```

----
### FTS a Replicator

```log
03:17:31.325215| [Sync]: {475} {Coll#-1} pushStatus=stopped, pullStatus=busy, progress=71634173/77493323/3163
....
03:17:31.897945| [Sync]: {475} {Coll#0} Saved remote checkpoint 'cp-iPGeXvAasonteuhaosteuhasoth=' as rev='76-cc'
.....
03:17:34.271595| [Sync]: {475} {Coll#-1} now stopped
```

#### In the above log line if you want to track the {475} replicator / process do this query below.
----

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` = "Sync"
    AND logLine IS NOT MISSING
    AND SEARCH(rawLog, "*{475}*")
ORDER BY dt
```
----

#### Query to find any 'Errors' & `type` = "Sync" 

----

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` = "Sync"
    AND logLine IS NOT MISSING
    AND SEARCH(rawLog, "*{475}*")
    AND error IS NOT MISSING
ORDER BY dt
```

----------------------------------------------------------------------------------------------------------

### SLOW PULL SYNC ???

#### Run this query to see how CBL is inserting data when doing a pull sync

----------------------------------------------------------------------------------------------------------

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` = "Sync"
    AND logLine IS NOT MISSING
    AND syncCommitStats IS NOT MISSING
ORDER BY dt
```


----------------------------------------------------------------------------------------------------------

### RANGE or BETWEEN timestamps or log Line Numbers

#### "did you find a interesting error , but now you want a few log lines before and after it?"

----------------------------------------------------------------------------------------------------------
```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` IS NOT MISSING
    AND logLine BETWEEN 25 AND 350
ORDER BY dt
```


----------------------------------------------------------------------------------------------------------

### How Many Replicators were running?

### Now you can answer when and what SG or Peer CBL (URLs/ws/wss) did you connect to?
----------------------------------------------------------------------------------------------------------
```SQL
SELECT dt AS `date`,
       auth.username AS auth_username,
       auth.`type` auth_type,
       `endpoint`,
       COALESCE(replicationId,replicatorAddress) AS replicatorId,
       syncType,
       stateFrom,
       stateTo,
       error,
       errorCode,
       errorMessage,
       replicatorStatus
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `endpoint` IS NOT MISSING
ORDER BY dt
```


----------------------------------------------------------------------------------------------------------

### Tracking a Replicator

#### From the above query we can see the `replicationId` for a replicator. Example: `124`

----------------------------------------------------------------------------------------------------------
```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND 124 IN replicationIdsList
    AND receivedChanges IS NOT MISSING
ORDER BY dt
```


When the `replicationId` is not available we can use the `replicatorAddress`

```SQL
SELECT *
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND replicatorAddress = "0x67eb321"
ORDER BY dt
```

----------------------------------------------------------------------------------------------------------

### Replicator Count Document Recieved

#### From this query we can see the total changes received by a replicator. Example: `124`

----------------------------------------------------------------------------------------------------------
```SQL
SELECT SUM(receivedChanges) AS totalChanges
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND 124 IN replicationIdsList
    AND receivedChanges IS NOT MISSING
```


----------------------------------------------------------------------------------------------------------

### Group by Replicator (summarize events per replicator)

#### From this query we can see the total changes received by a replicator. Example: `124`
----------------------------------------------------------------------------------------------------------

```SQL
SELECT COALESCE(replicationId, replicatorAddress) AS replicatorId,
       `endpoint`,
       ARRAY_AGG({
           "date": dt,
           "syncType": syncType,
           "stateFrom": stateFrom,
           "stateTo": stateTo,
           "replicatorStatus": replicatorStatus,
           "error": error,
           "errorCode": errorCode,
           "errorMessage": errorMessage
       }) AS events
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `endpoint` IS NOT MISSING
GROUP BY COALESCE(replicationId, replicatorAddress), `endpoint`
ORDER BY MIN(dt)
```

----------------------------------------------------------------------------------------------------------

### Error Query

##### This query will show all errors and their timestamps
----------------------------------------------------------------------------------------------------------

```SQL
SELECT dt as `date`,
       `type`,
       COALESCE(replicationId, replicatorAddress) AS replicatorId,
       syncType,
       errorCode,
       errorMessage,
       rawLog
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `error` = true
ORDER BY dt
```

----------------------------------------------------------------------------------------------------------

### Group by Error Message

##### This query will group by the error message and show the number of errors and the timestamps
----------------------------------------------------------------------------------------------------------

```SQL
SELECT `type`,
       errorMessage,
       COUNT(*) AS errorCount,
       ARRAY_AGG(dt) AS timestamps,
       ARRAY_AGG(rawLog) AS logs
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `error` = true
GROUP BY `type`, errorMessage
ORDER BY errorCount DESC
```


----------------------------------------------------------------------------------------------------------

### Bar Chart Query: to find any 'Errors' & `type` = "Sync" 

##### This query will show you the number of sync events by `syncType`
----------------------------------------------------------------------------------------------------------

```SQL
SELECT syncType, COUNT(*) AS eventCount
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND SPLIT(`type`,":")[0] = "Sync"
GROUP BY syncType
HAVING COUNT(*) > 0
ORDER BY eventCount DESC
```



----------------------------------------------------------------------------------------------------------

### Bar Chart Query: Events by Time

##### This query will show you the number of sync events by time
----------------------------------------------------------------------------------------------------------

```SQL
SELECT SUBSTR(dt, 0, 5) AS timeBucket, 
       COUNT(*) AS syncCount
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
     AND SPLIT(`type`,":")[0] = "Sync"
GROUP BY SUBSTR(dt, 0, 5)
ORDER BY timeBucket
```


----------------------------------------------------------------------------------------------------------

### Bar Chart Query: Errors by Time

##### This query will show you the number of error events by time
----------------------------------------------------------------------------------------------------------

```SQL
SELECT SUBSTR(dt, 0, 8) AS timeBucket,  
       COUNT(*) AS errorCount
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND error = true
GROUP BY SUBSTR(dt, 0, 8)
ORDER BY timeBucket
```
