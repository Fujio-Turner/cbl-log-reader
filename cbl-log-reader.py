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
            return self.cbColl.upsert(key,doc,expiry=timedelta(seconds=ttl))
        except CouchbaseException as e:
            print(f'UPSERT operation failed: {e}')
            print("no insert for:" , key)
            return False

    def is_start_of_new_log_line(self, line):
        # Regex pattern to match the timestamp, pipe, and space
        pattern = r'^\d{2}:\d{2}:\d{2}\.\d{6}\| '
        return re.match(pattern, line) is not None
    
    def find_type(self, line, is_full_date):
        if is_full_date:
            # For CBL 3.2.0 with ISO-8601 timestamp, type follows timestamp and pipe
            pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+(?:Z|[+-]\d{2}:\d{2})?\|\s*([^\s:]+)'
            match = re.search(pattern, line)
            return match.group(1) if match else None
        else:
            # For CBL 3.1.0 with time-only, type is in brackets
            pattern = r'\[([^\]]+)\]'
            match = re.search(pattern, line)
            return match.group(1) if match else None
    
    def extract_timestamp(self, log_line):
        # Try ISO-8601 full date format first (e.g., 2023-10-05T17:13:21.384768Z)
        full_date_pattern = r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+(?:Z|[+-]\d{2}:\d{2})?)\|'
        full_date_match = re.search(full_date_pattern, log_line)
        if full_date_match:
            return [full_date_match.group(1), True]
        
        # Fall back to older time-only format (e.g., 17:13:21.384768)
        time_only_pattern = r'^(\d{2}:\d{2}:\d{2}\.\d+)\|'
        time_only_match = re.search(time_only_pattern, log_line)
        if time_only_match:
            return [time_only_match.group(1), False]
        
        # No match found
        return [None, False]
    
    def find_error_in_line(self, line, is_full_date):
        # Check for the end-of-line error condition first (preserving your logic)
        if self.check_error_end_of_line(line):
            return False

        if is_full_date:
            # For CBL 3.2.0: Type "Sync" or "WS" followed by ERROR without brackets
            if (re.search(r'(Sync|WS)\s*ERROR(?:\s|:|$)', line, re.IGNORECASE) or 
                re.search(r' error', line, re.IGNORECASE)):
                return True
        else:
            # For CBL 3.1.0: [Sync] or [WS] followed by ERROR with brackets
            if (re.search(r'\[(Sync|WS)\]\s*ERROR(?:\s|:|$)', line, re.IGNORECASE) or 
                re.search(r' error', line, re.IGNORECASE)):
                return True
        
        # Return False if no error patterns are found
        return False

    def find_pattern_query_line_1(self, line, is_full_date):
        if is_full_date:
            # For CBL 3.2.0: "Query" followed by {text} and --> after timestamp, no brackets or pipe needed here
            pattern = r'Query\s*\{(.+?)\}\s*-->'
        else:
            # For CBL 3.1.0: [Query]: followed by {text} with brackets, pipe included
            pattern = r'\| \[Query\]:\s*\{(.+?)\}\s*-->'
        
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
        
    def getSyncConfig(self, line):
        config_data = []
        # Updated pattern to handle unquoted Push/Pull values and optional Options
        pattern = r'\{Coll#(\d+)\}\s*"([^"]+)":\s*\{(?:[^}]*?)"?Push"?:\s*([^,]+),\s*"?Pull"?:\s*([^,]+),\s*Options=\{([^}]*)\}'
        matches = re.finditer(pattern, line)
        
        for match in matches:
            coll_num = int(match.group(1))
            coll_name = match.group(2)
            push_val = match.group(3).strip()
            pull_val = match.group(4).strip()
            options_str = match.group(5).strip()
            
            # Parse options into a dictionary (if present)
            options_dict = {}
            if options_str:  # Only process if Options isn’t empty
                options_pattern = r'(\w+)\s*:\s*"([^"]+)"|(\w+)\s*:\s*([^\s,]+)'
                for opt_match in re.finditer(options_pattern, options_str):
                    if opt_match.group(1) and opt_match.group(2):  # key:"value"
                        options_dict[opt_match.group(1)] = opt_match.group(2)
                    elif opt_match.group(3) and opt_match.group(4):  # key:value
                        options_dict[opt_match.group(3)] = opt_match.group(4)
            
            config_data.append({
                "coll": coll_num,
                "name": coll_name,
                "push": push_val,
                "pull": pull_val,
                "options": options_dict
            })
        return config_data

        
    def bigLineProcecess(self, line, seq):
        if self.debug:
            print(line)

        newData = {}
        newData["logLine"] = seq
        timestamp_result = self.extract_timestamp(line)
        newData["dt"] = timestamp_result[0]  # First element is the timestamp
        newData["fullDate"] = timestamp_result[1]  # Second element is the fullDate flag
        newData["type"] = self.find_type(line, timestamp_result[1])
        is_full_date = timestamp_result[1]  # For convenience in regex conditions

        ### ERRORs ######
        if self.find_error_in_line(line, is_full_date):  # Pass is_full_date here
            newData["error"] = True
            eType = line.split("ERROR: ")
            if line.find("SQLite error (code 14)") != -1:
                newData["errorType"] = "SQLite error (code 14) [edit] Opening DB"
            else:
                if len(eType) > 1:
                    newData["errorType"] = eType[1]

        newData["fileName"] = self.log_file_name

        if newData["type"] == "Sync":
            ###### Sync Start ######
            if 'Starting Replicator' and 'config:' in line:
                newData["syncType"] = "Start"
                newData["replicationConfig"] = self.getSyncConfig(line)

                # Extract single replicationId for Starting Replicator lines
                if is_full_date:
                    # For CBL 3.2.0: Type "Sync" followed by {id|
                    repl_id_match = re.search(r'Sync\s*\{(\d+)(?:\|)?', line)
                else:
                    # For CBL 3.1.0: [Sync]: followed by {id|
                    repl_id_match = re.search(r'\[Sync\]:\s*\{(\d+)(?:\|)?', line)
                if repl_id_match:
                    newData["replicationId"] = int(repl_id_match.group(1))

                ### Bottom of Config #####
                auth_match = re.search(r'auth:\{(?:.*,)?\s*type:"(.*?)",\s*username:"(.*?)"(?:,.*?session:"(.*?)")?.*?\}', line)
                if auth_match:
                    auth_dict = {
                        "type": auth_match.group(1),
                        "username": auth_match.group(2)
                    }
                    if auth_match.group(3):
                        auth_dict["session"] = auth_match.group(3)
                    newData["auth"] = auth_dict

                endpoint_match = re.search(r'endpoint:\s*([^\s}]+)', line)
                if endpoint_match:
                    endpoint_value = endpoint_match.group(1).strip()
                    newData["endpoint"] = endpoint_value.rstrip(',')

                self_signed_match = re.search(r'onlySelfSignedServer:(true|false)', line)
                if self_signed_match:
                    newData["onlySelfSignedServer"] = self_signed_match.group(1) == 'true'

            ###### Extract Replication IDs and Collection Number for Non-Start Lines ######
            else:
                if is_full_date:
                    # For CBL 3.2.0: Type "Sync" followed by {id|/path/with#ids/} or just {id}
                    repl_ids_match = re.search(r'Sync\s*\{(?:\d+\|)?([^}]+)\}', line)
                    single_id_match = re.search(r'Sync\s*\{(\d+)\}', line)
                else:
                    # For CBL 3.1.0: [Sync]: followed by {id|/path/with#ids/} or just {id}
                    repl_ids_match = re.search(r'\[Sync\]:\s*\{(?:\d+\|)?([^}]+)\}', line)
                    single_id_match = re.search(r'\[Sync\]:\s*\{(\d+)\}', line)
                
                if single_id_match and "State:" in line:
                    # Handle single ID with State and progress (e.g., {15790} State: busy, progress=99.9506%)
                    newData["replicationId"] = int(single_id_match.group(1))
                    state_match = re.search(r'State:\s*(\w+)', line)
                    if state_match:
                        newData["state"] = state_match.group(1)
                    progress_match = re.search(r'progress=([\d.]+)%', line)
                    if progress_match:
                        newData["progress"] = float(progress_match.group(1)) / 100  # Convert percentage to decimal
                elif repl_ids_match:
                    # Handle multi-ID path (e.g., {16033|/JRepl@.../RevFinder#16033/})
                    repl_ids_dict = {}
                    repl_ids_list = []
                    path = repl_ids_match.group(1)
                    # Match patterns like C4RemoteRepl#id, Repl#id, Pusher#id, Puller#id, RevFinder#id
                    path_ids = re.findall(r'(C4RemoteRepl|Repl|Pusher|Puller|RevFinder)#(\d+)', path)
                    for name, id_value in path_ids:
                        id_int = int(id_value)
                        repl_ids_dict[name] = id_int
                        if id_int not in repl_ids_list:  # Avoid duplicates in the list
                            repl_ids_list.append(id_int)
                    
                    newData["replicationIds"] = repl_ids_dict
                    newData["replicationIdsList"] = repl_ids_list

                # Extract Collection Number (e.g., Coll=0 or Coll=1)
                coll_match = re.search(r'Coll=(\d+)', line)
                if coll_match:
                    newData["collection"] = int(coll_match.group(1))

                # Extract Received Changes (e.g., Received 200 changes)
                received_changes_match = re.search(r'Received\s+(\d+)\s+changes', line)
                if received_changes_match:
                    newData["receivedChanges"] = int(received_changes_match.group(1))

            # ... (rest of the Sync block remains unchanged: repActiveStats, repClassStats, sCs)

            ###### Sync Start ######
            if 'Starting Replicator' and 'config:' in line:
                newData["syncType"] = "Start"
                newData["replicationConfig"] = self.getSyncConfig(line)

                ### Bottom of Config #####
                auth_match = re.search(r'auth:\{(?:.*,)?\s*type:"(.*?)",\s*username:"(.*?)"(?:,.*?session:"(.*?)")?.*?\}', line)
                if auth_match:
                    auth_dict = {
                        "type": auth_match.group(1),
                        "username": auth_match.group(2)
                    }
                    if auth_match.group(3):
                        auth_dict["session"] = auth_match.group(3)
                    newData["auth"] = auth_dict

                endpoint_match = re.search(r'endpoint:\s*([^\s}]+)', line)
                if endpoint_match:
                    endpoint_value = endpoint_match.group(1).strip()
                    newData["endpoint"] = endpoint_value.rstrip(',')

                self_signed_match = re.search(r'onlySelfSignedServer:(true|false)', line)

                if self_signed_match:
                    newData["onlySelfSignedServer"] = self_signed_match.group(1) == 'true'

            repActiveStats = self.replication_status_stats(line)

            if repActiveStats:
                newData["syncType"] = "Active"
                newData["replicatorStatus"] = repActiveStats

            repClassStats = self.replicator_class_status(line)
            if repClassStats:
                newData["syncType"] = "Status"
                newData["replicatorClassStatus"] = repClassStats

            sCs = self.sync_commit_stats_get(line)
            if sCs:
                newData["syncType"] = "Commit"
                newData["syncCommitStats"] = {
                    "numInserts": sCs[0],
                    "insertPerSec": sCs[2],
                    "insertTime_ms": sCs[1],
                    "avgPerInsert_ms": round(sCs[1] / sCs[0], 3)
                }

        ######## QUERY ##########
        if newData["type"] == "Query":
            a = self.find_pattern_query_line_1(line, is_full_date)
            if a == True:
                b = line.split(" --> ")
                newData["queryInfo"] = json.loads(b[1])

            queryExeStats = self.extract_query_info(line)
            if queryExeStats:
                newData["queryExeStats"] = queryExeStats

        ##### CHANGES ######
        if newData["type"] == "Changes":
            # Replication ID extraction
            if is_full_date:
                # For CBL 3.2.0: Type "Changes" followed by {number} or {number| after timestamp
                repl_id_match = re.search(r'Changes\s*\{(\d+)(?:\|)?', line)
            else:
                # For CBL 3.1.0: [Changes]: followed by {number} or {number|
                repl_id_match = re.search(r'\[Changes\]:\s*\{(\d+)(?:\|)?', line)
            if repl_id_match:
                newData["replicationId"] = int(repl_id_match.group(1))

        ###### BLIPMESSAGES #######
        if newData["type"] == "BLIPMessages":
            # Extract the subtype (RECEIVED, SENDING, etc.) after [BLIPMessages]:
            if is_full_date:
                # For CBL 3.2.0: BLIPMessages followed by subtype
                type_match = re.search(r'BLIPMessages\s*(\w+):', line)
            else:
                # For CBL 3.1.0: [BLIPMessages]: followed by subtype
                type_match = re.search(r'\[BLIPMessages\]:\s*(\w+):', line)
            if type_match:
                newData["blipMessageType"] = type_match.group(1)

            # Extract replicationId from REQ #number
            repl_id_match = re.search(r'REQ #(\d+)', line)
            if repl_id_match:
                newData["replicationId"] = int(repl_id_match.group(1))

            # Extract Profile
            profile_match = re.search(r'Profile:\s*(\S+)', line)
            if profile_match:
                newData["profile"] = profile_match.group(1)

            # Extract collection
            collection_match = re.search(r'collection:\s*(\d+)', line)
            if collection_match:
                newData["collection"] = int(collection_match.group(1))

            # Extract batch
            batch_match = re.search(r'batch:\s*(\d+)', line)
            if batch_match:
                newData["batch"] = int(batch_match.group(1))

            # Extract sendReplacementRevs
            send_repl_match = re.search(r'sendReplacementRevs:\s*(\d+)', line)
            if send_repl_match:
                newData["sendReplacementRevs"] = int(send_repl_match.group(1))

            # Extract versioning
            versioning_match = re.search(r'versioning:\s*(\S+)', line)
            if versioning_match:
                newData["versioning"] = versioning_match.group(1)

            # Extract activeOnly
            active_match = re.search(r'activeOnly:\s*(true|false)', line)
            if active_match:
                newData["activeOnly"] = active_match.group(1) == 'true'

            # Extract revocations
            revocations_match = re.search(r'revocations:\s*(true|false)', line)
            if revocations_match:
                newData["revocations"] = revocations_match.group(1) == 'true'

            # Extract filter
            filter_match = re.search(r'filter:\s*(\S+)', line)
            if filter_match:
                newData["filter"] = filter_match.group(1)

            # Extract channels and split into array
            channels_match = re.search(r'channels:\s*([^\n}]+)', line)
            if channels_match:
                channels_str = channels_match.group(1).strip()
                newData["channels"] = channels_str.split(',')

            # For RECEIVED-specific fields (only if present)
            id_match = re.search(r'id:\s*(\S+)', line)
            if id_match:
                newData["_id"] = id_match.group(1)

            rev_match = re.search(r'rev:\s*(\S+)', line)
            if rev_match:
                newData["_rev"] = rev_match.group(1)

            sequence_match = re.search(r'sequence:\s*"([^"]+)"', line)
            if sequence_match:
                newData["sequence"] = sequence_match.group(1)

            history_match = re.search(r'history:\s*([^\n]+)', line)
            if history_match:
                history_str = history_match.group(1)
                newData["history"] = history_str.split(',')

            # For RECEIVED-specific fields
            id_match = re.search(r'id:\s*(\S+)', line)
            if id_match:
                newData["_id"] = id_match.group(1)

            rev_match = re.search(r'rev:\s*(\S+)', line)
            if rev_match:
                newData["_rev"] = rev_match.group(1)

            sequence_match = re.search(r'sequence:\s*"([^"]+)"', line)
            if sequence_match:
                newData["sequence"] = sequence_match.group(1)

            history_match = re.search(r'history:\s*([^\n]+)', line)
            if history_match:
                history_str = history_match.group(1)
                newData["history"] = history_str.split(',')

        newData["rawLog"] = line

        dict_string = json.dumps(newData, sort_keys=True)
        cbKey = uuid.uuid5(uuid.NAMESPACE_DNS, dict_string)
        self.cbUpsert(str(cbKey), newData, self.cbTtl)

    def read_log(self):
        print('Log Processing: ',self.log_file_name)
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