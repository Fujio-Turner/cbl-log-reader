import sys
import json
import datetime, time
import re
from datetime import datetime
from datetime import timedelta
import uuid
import time


from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import (ClusterOptions, ClusterTimeoutOptions, QueryOptions)
from couchbase.exceptions import CouchbaseException

class LogReader():

    cb = None
    cbColl = None
    cbHost = "127.0.0.1"
    cbUser = "Administrator"
    cbPass = "fujiofujio"
    cbBucketName = "cbl-log-reader"
    cbScopeName = "_default"
    cbCollectionName = "_default"
    cbTtl = 86400
    log_file_name = "cbl-log-big.txt"

    def __init__(self, file):
        self.readConfigFile(file)
        self.makeCB()

    def readConfigFile(self,configFile):
        a = open(configFile, "rb" )
        b = json.loads(a.read())
        self.cbHost = b["cb-cluster-host"]
        self.cbBucketName = b["cb-bucket-name"]
        self.cbUser = b["cb-bucket-user"]
        self.cbPass = b["cb-bucket-user-password"]
        self.debug = b["debug"]
        self.cbTtl = b['cb-expire']
        self.log_file_name = b['file-to-parse']
        a.close()

    def makeCB(self):

        try:
            auth = PasswordAuthenticator(self.cbUser, self.cbPass)
            cluster = Cluster('couchbase://'+self.cbHost, ClusterOptions(auth))
            cluster.wait_until_ready(timedelta(seconds=5))
            self.cb = cluster.bucket(self.cbBucketName)
			#bucket.scope(self.cbScopeName).collection(self.cbCollectionName)
            self.cbColl = self.cb.default_collection()
            #return cluster , self.cb
        except CouchbaseException as ex:
            print("nope CB",ex)
            exit()

    def cbUpsert(self,key,doc,ttl=0):
		#opts = InsertOptions(timeout=timedelta(seconds=5))
        try:
            r = self.cbColl.upsert(key,doc,expiry=timedelta(seconds=ttl))
            return r
        except CouchbaseException as e:
            print(f'UPSERT operation failed: {e}')
            print("no insert for:" , key)
            return False

    def is_start_of_new_log_line(self, line):
        # Regex pattern to match the timestamp, pipe, and space
        pattern = r'^\d{2}:\d{2}:\d{2}\.\d{6}\| '
        return re.match(pattern, line) is not None
    
    def find_string_in_brackets(self,text):
        # Define the regex pattern
        #pattern = r'\s\[(.*?)\]:\s'
        pattern = r' \[([^\]]+)\]'
        # Search for the pattern in the text
        match = re.search(pattern, text)
        # If a match is found, return the captured group, otherwise return None
        return match.group(1) if match else None
    
    def extract_timestamp(self,log_line):
        pattern = r'^(\d{2}:\d{2}:\d{2}\.\d+)\|'
        match = re.search(pattern, log_line)
        return match.group(1) if match else None
    
    def find_error_in_line(self,line):
        # Search for the pattern in the line

        if self.check_error_end_of_line(line):
            return False

        matches = [m.start() for m in re.finditer(r' error', line, re.IGNORECASE)]
        # Return True if matches are found, False otherwise
        return bool(matches)
    
    def find_pattern_query_line_1(self,line):
        #pattern = r"\| \[Query\]: \{(\d+)\} -->"
        pattern = r"\| \[Query\]: \{(.+?)\} -->"
        result = re.search(pattern, line)
        if result:
            return True
        else:
            return False
    
    def check_error_end_of_line(self,log_line):
        return log_line.endswith(', error: (null)')
    
    def sync_commit_stats_get(self,log_line):
        # Look for 'commit' at the end of the line and extract the relevant stats
        match = re.search(r'Inserted (\d+) revs in ([\d.]+)ms \(([\d.]+)/sec\)', log_line)
        if match and 'commit' in log_line:
            # Extract the number of revs inserted, time taken to insert, and inserts per second
            num_revs_inserted = int(match.group(1))
            time_taken = float(match.group(2))
            inserts_per_second = float(match.group(3))
            return [num_revs_inserted, time_taken, inserts_per_second]
        else:
            return None
        
    def replication_status_stats(self,log_line):
        # Define a regular expression pattern to match key-value pairs
        pattern = re.compile(r'(\w+)=((?:.*?)(?=\s\w+=|$))')
        
        # Use the findall method to extract all key-value pairs from the log line
        matches = pattern.findall(log_line)
        
        # Convert the list of tuples into a dictionary, converting values to integers when appropriate
        stats_dict = {}
        for key, value in matches:
            value = value.strip().rstrip(':').replace(',', '')  # Clean up the value and remove commas
            try:
                # Try to convert the value to an integer
                stats_dict[key] = int(value)
            except ValueError:
                # If conversion fails, keep the value as a string
                stats_dict[key] = value
        
        # Check if 'activityLevel' key exists in the dictionary
        if 'activityLevel' not in stats_dict:
            return False
        
        return stats_dict

    
    def replicator_class_status(self,log_line):
        pattern = r'pushStatus=([a-zA-Z]+), pullStatus=([a-zA-Z]+), progress=(\d+/\d+(?:/\d+)?)'
        match = re.search(pattern, log_line)
        if match:
            push_status = match.group(1)
            pull_status = match.group(2)
            progress = match.group(3).split('/')
            status = 0
            if int(progress[1]) > 0:
                status = round(int(progress[0])/int(progress[1]),4)
            data = {
                'pushStatus': push_status,
                'pullStatus': pull_status,
                'progress': {
                    'completed': int(progress[0]),
                    'total': int(progress[1]),
                    'status':status
                }
            }
            if len(progress) == 3:
                data['progress']['docsPushed'] = progress[2]
            return data
        else:
            return False
        
    def extract_query_info(self,log_line):
        pattern = r"Created on \{Query#\d+\} with (\d+) rows \((\d+) bytes\) in ([\d.]+)ms"
        match = re.search(pattern, log_line)
        if match:
            rows = int(match.group(1))
            bytes_amount = int(match.group(2))
            time_ms = float(match.group(3))
            return {"rows": rows, "bytes": bytes_amount, "time_ms": time_ms}
        else:
            return False

        
    def bigLineProcecess(self,line,seq):

        if self.debug:
            print(line)

        newData = {}
        newData["logLine"] = seq
        newData["dt"] = self.extract_timestamp(line)
        newData["type"] = self.find_string_in_brackets(line)

        if(self.find_error_in_line(line)):
            newData["error"] = True
            eType = line.split("ERROR: ") 
            if line.find("SQLite error (code 14)") != -1:
                newData["errorType"] = "SQLite error (code 14) [edit] Opening DB"
            else:
                if len(eType) > 1:
                    newData["errorType"] = eType[1]

        newData["fileName"] = self.log_file_name

        if newData["type"] == "Sync":
            
            repActiveStats = False
            repActiveStats = self.replication_status_stats(line)
            if repActiveStats:
                newData["replicatorStatus"] = repActiveStats
            
            repClassStats = self.replicator_class_status(line)
            if repClassStats:
                newData["replicatorClassStatus"] = repClassStats
        
            sCs = self.sync_commit_stats_get(line)
            if sCs:
                newData["syncCommitStats"] = {"numInserts":sCs[0],"insertPerSec":sCs[2],"insertTime_ms":sCs[1],"avgPerInsert_ms":round(sCs[1]/sCs[0],3)}
                
        if newData['type'] == "Query":
            a = self.find_pattern_query_line_1(line)
            if a == True:
                b = line.split(" --> ")
                newData["queryInfo"] = json.loads(b[1])

            queryExeStats = self.extract_query_info(line)
            if queryExeStats:
                newData["queryExeStats"] = queryExeStats

        newData["rawLog"] = line

        dict_string = json.dumps(newData, sort_keys=True)
        cbKey = uuid.uuid5(uuid.NAMESPACE_DNS , dict_string)
        self.cbUpsert(str(cbKey),newData,self.cbTtl)


    def read_log(self):
        print('Start of CBL Log Reader: ',datetime.now())
        start = time.time()
        with open(self.log_file_name, "r") as log_file:
            json_lines = ""
            inside_json = False
            seq = 1

            for line in log_file:
                line = line.rstrip('\r\n')

                # Check if the line is the start of a new log line
                if self.is_start_of_new_log_line(line):
                    # If we were inside a JSON-like structure, print it before starting the new log line
                    if inside_json:
                        #print(json_lines)
                        json_lines = ""
                        inside_json = False
                    
                    self.bigLineProcecess(line,seq)
                    seq += 1
                else:
                    # If the line is not the start of a new log line, it may be part of a JSON-like structure
                    inside_json = True
                    json_lines += line
           
            # In case the file ends while still inside a JSON-like structure
            if inside_json:
                self.bigLineProcecess(line,seq)
                seq += 1
        end = time.time()
        print('End of CBL Log Reader  : ',datetime.now())
        print('Total Process Time(sec): ',end - start)
        print('Log Lines Processed    : ', seq)           
 

# Example usage
if __name__ == "__main__":
    if len(sys.argv) > 1:
        cblFile = sys.argv[1]
    else:
        print("Error: No cbl file file given")
        exit()
    log_reader = LogReader(cblFile)
    log_reader.read_log()