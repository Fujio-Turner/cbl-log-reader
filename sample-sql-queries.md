
----------------------------------------------------------------------------------------------------------

### Create this index to `cbl-log-reader` bucket with below queries

----------------------------------------------------------------------------------------------------------
```SQL
CREATE INDEX `cblDtRange_v5` ON `cbl-log-reader`(`dt`,`logLine`,`type`,`error`,`fileName`)
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
SELECT COUNT(errorType) as cError, errorType
FROM `cbl-log-reader`
WHERE dt IS NOT MISSING
    AND `type` IS NOT MISSING
    AND logLine IS NOT MISSING
    AND error IS not MISSING
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
    AND `error` IS NOT MISSING
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