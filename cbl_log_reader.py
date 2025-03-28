import sys
import json
import datetime
import time
import re
import os
from datetime import datetime, timedelta
import uuid

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
    file_parse_type = "info|error|debug|verbose|warning"

    def __init__(self, config_file):
        self.readConfigFile(config_file)
        self.makeCB()

    def readConfigFile(self, configFile):
        with open(configFile, "rb") as f:
            config = json.loads(f.read())
            self.cbHost = config["cb-cluster-host"]
            self.cbBucketName = config["cb-bucket-name"]
            self.cbUser = config["cb-bucket-user"]
            self.cbPass = config["cb-bucket-user-password"]
            self.debug = config["debug"]
            self.cbTtl = config['cb-expire']
            self.file_to_parse = config['file-to-parse']
            self.file_parse_type = config.get('file-parse-type', "info|error|debug|verbose|warning")

    def makeCB(self):
        try:
            auth = PasswordAuthenticator(self.cbUser, self.cbPass)
            cluster = Cluster('couchbase://' + self.cbHost, ClusterOptions(auth))
            cluster.wait_until_ready(timedelta(seconds=5))
            self.cb = cluster.bucket(self.cbBucketName)
            self.cbColl = self.cb.default_collection()
        except CouchbaseException as ex:
            print("Failed to connect to Couchbase:", ex)
            exit()

    def cbUpsert(self, key, doc, ttl=0):
        try:
            return self.cbColl.upsert(key, doc, expiry=timedelta(seconds=ttl))
        except CouchbaseException as e:
            print(f'UPSERT operation failed: {e}')
            print("No insert for:", key)
            return False

    def is_start_of_new_log_line(self, line):
        pattern = r'^\d{2}:\d{2}:\d{2}\.\d{6}\| '
        return re.match(pattern, line) is not None
    
    def find_type(self, line, is_full_date):
        if is_full_date:
            pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+(?:Z|[+-]\d{2}:\d{2})?\|\s*([^\s:]+)'
            match = re.search(pattern, line)
            return match.group(1) if match else None
        else:
            pattern = r'\[([^\]]+)\]'
            match = re.search(pattern, line)
            return match.group(1) if match else None
    
    def extract_timestamp(self, log_line):
        full_date_pattern = r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+(?:Z|[+-]\d{2}:\d{2})?)\|'
        full_date_match = re.search(full_date_pattern, log_line)
        if full_date_match:
            return [full_date_match.group(1), True]
        time_only_pattern = r'^(\d{2}:\d{2}:\d{2}\.\d+)\|'
        time_only_match = re.search(time_only_pattern, log_line)
        if time_only_match:
            return [time_only_match.group(1), False]
        return [None, False]
    
    def find_error_in_line(self, line, is_full_date):
        if self.check_error_end_of_line(line):
            return False
        if is_full_date:
            if (re.search(r'(Sync|WS)\s*ERROR(?:\s|:|$)', line, re.IGNORECASE) or 
                re.search(r' error', line, re.IGNORECASE)):
                return True
        else:
            if (re.search(r'\[(Sync|WS)\]\s*ERROR(?:\s|:|$)', line, re.IGNORECASE) or 
                re.search(r' error', line, re.IGNORECASE)):
                return True
        return False

    def find_pattern_query_line_1(self, line, is_full_date):
        if is_full_date:
            pattern = r'Query\s*\{(.+?)\}\s*-->'
        else:
            pattern = r'\| \[Query\]:\s*\{(.+?)\}\s*-->'
        result = re.search(pattern, line)
        return bool(result)
    
    def check_error_end_of_line(self, log_line):
        return log_line.endswith(', error: (null)')
    
    def sync_commit_stats_get(self, log_line):
        match = re.search(r'Inserted (\d+) revs in ([\d.]+)ms \(([\d.]+)/sec\)', log_line)
        if match and 'commit' in log_line:
            return [int(match.group(1)), float(match.group(2)), float(match.group(3))]
        return None
        
    def replication_status_stats(self, log_line):
        pattern = re.compile(r'(\w+)=((?:.*?)(?=\s\w+=|$))')
        matches = pattern.findall(log_line)
        stats_dict = {}
        for key, value in matches:
            value = value.strip().rstrip(':').replace(',', '')
            try:
                stats_dict[key] = int(value)
            except ValueError:
                stats_dict[key] = value
        return stats_dict if 'activityLevel' in stats_dict else False

    def replicator_class_status(self, log_line):
        pattern = r'pushStatus=([a-zA-Z]+), pullStatus=([a-zA-Z]+), progress=(\d+/\d+(?:/\d+)?)'
        match = re.search(pattern, log_line)
        if match:
            push_status = match.group(1)
            pull_status = match.group(2)
            progress = match.group(3).split('/')
            status = 0
            if int(progress[1]) > 0:
                status = round(int(progress[0])/int(progress[1]), 4)
            data = {
                'pushStatus': push_status,
                'pullStatus': pull_status,
                'progress': {
                    'completed': int(progress[0]),
                    'total': int(progress[1]),
                    'status': status
                }
            }
            if len(progress) == 3:
                data['progress']['docsPushed'] = progress[2]
            return data
        return False
        
    def extract_query_info(self, log_line):
        pattern = r"Created on \{Query#\d+\} with (\d+) rows \((\d+) bytes\) in ([\d.]+)ms"
        match = re.search(pattern, log_line)
        if match:
            return {"rows": int(match.group(1)), "bytes": int(match.group(2)), "time_ms": float(match.group(3))}
        return False
        
    def getSyncConfig(self, line):
        config_data = []
        pattern = r'\{Coll#(\d+)\}\s*"([^"]+)":\s*\{(?:[^}]*?)"?Push"?:\s*([^,]+),\s*"?Pull"?:\s*([^,]+),\s*Options=\{([^}]*)\}'
        matches = re.finditer(pattern, line)
        for match in matches:
            coll_num = int(match.group(1))
            coll_name = match.group(2)
            push_val = match.group(3).strip()
            pull_val = match.group(4).strip()
            options_str = match.group(5).strip()
            options_dict = {}
            if options_str:
                options_pattern = r'(\w+)\s*:\s*"([^"]+)"|(\w+)\s*:\s*([^\s,]+)'
                for opt_match in re.finditer(options_pattern, options_str):
                    if opt_match.group(1) and opt_match.group(2):
                        options_dict[opt_match.group(1)] = opt_match.group(2)
                    elif opt_match.group(3) and opt_match.group(4):
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
        newData["dt"] = timestamp_result[0]
        newData["fullDate"] = timestamp_result[1]
        newData["type"] = self.find_type(line, timestamp_result[1])
        is_full_date = timestamp_result[1]

        ### ERRORs ######
        if self.find_error_in_line(line, is_full_date):
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

                if is_full_date:
                    repl_id_match = re.search(r'Sync\s*\{(\d+)(?:\|)?', line)
                else:
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
                    repl_ids_match = re.search(r'Sync\s*\{(?:\d+\|)?([^}]+)\}', line)
                    single_id_match = re.search(r'Sync\s*\{(\d+)\}', line)
                else:
                    repl_ids_match = re.search(r'\[Sync\]:\s*\{(?:\d+\|)?([^}]+)\}', line)
                    single_id_match = re.search(r'\[Sync\]:\s*\{(\d+)\}', line)
                
                if single_id_match and "State:" in line:
                    newData["replicationId"] = int(single_id_match.group(1))
                    state_match = re.search(r'State:\s*(\w+)', line)
                    if state_match:
                        newData["state"] = state_match.group(1)
                    progress_match = re.search(r'progress=([\d.]+)%', line)
                    if progress_match:
                        newData["progress"] = float(progress_match.group(1)) / 100
                elif repl_ids_match:
                    repl_ids_dict = {}
                    repl_ids_list = []
                    path = repl_ids_match.group(1)
                    path_ids = re.findall(r'(C4RemoteRepl|Repl|Pusher|Puller|RevFinder)#(\d+)', path)
                    for name, id_value in path_ids:
                        id_int = int(id_value)
                        repl_ids_dict[name] = id_int
                        if id_int not in repl_ids_list:
                            repl_ids_list.append(id_int)
                    
                    newData["replicationIds"] = repl_ids_dict
                    newData["replicationIdsList"] = repl_ids_list

                coll_match = re.search(r'Coll=(\d+)', line)
                if coll_match:
                    newData["collection"] = int(coll_match.group(1))

                received_changes_match = re.search(r'Received\s+(\d+)\s+changes', line)
                if received_changes_match:
                    newData["receivedChanges"] = int(received_changes_match.group(1))

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
            if a:
                b = line.split(" --> ")
                newData["queryInfo"] = json.loads(b[1])

            queryExeStats = self.extract_query_info(line)
            if queryExeStats:
                newData["queryExeStats"] = queryExeStats

        ##### CHANGES ######
        if newData["type"] == "Changes":
            if is_full_date:
                repl_id_match = re.search(r'Changes\s*\{(\d+)(?:\|)?', line)
            else:
                repl_id_match = re.search(r'\[Changes\]:\s*\{(\d+)(?:\|)?', line)
            if repl_id_match:
                newData["replicationId"] = int(repl_id_match.group(1))

        ###### BLIPMESSAGES #######
        if newData["type"] == "BLIPMessages":
            if is_full_date:
                type_match = re.search(r'BLIPMessages\s*(\w+):', line)
            else:
                type_match = re.search(r'\[BLIPMessages\]:\s*(\w+):', line)
            if type_match:
                newData["blipMessageType"] = type_match.group(1)

            repl_id_match = re.search(r'REQ #(\d+)', line)
            if repl_id_match:
                newData["replicationId"] = int(repl_id_match.group(1))

            profile_match = re.search(r'Profile:\s*(\S+)', line)
            if profile_match:
                newData["profile"] = profile_match.group(1)

            collection_match = re.search(r'collection:\s*(\d+)', line)
            if collection_match:
                newData["collection"] = int(collection_match.group(1))

            batch_match = re.search(r'batch:\s*(\d+)', line)
            if batch_match:
                newData["batch"] = int(batch_match.group(1))

            send_repl_match = re.search(r'sendReplacementRevs:\s*(\d+)', line)
            if send_repl_match:
                newData["sendReplacementRevs"] = int(send_repl_match.group(1))

            versioning_match = re.search(r'versioning:\s*(\S+)', line)
            if versioning_match:
                newData["versioning"] = versioning_match.group(1)

            active_match = re.search(r'activeOnly:\s*(true|false)', line)
            if active_match:
                newData["activeOnly"] = active_match.group(1) == 'true'

            revocations_match = re.search(r'revocations:\s*(true|false)', line)
            if revocations_match:
                newData["revocations"] = revocations_match.group(1) == 'true'

            filter_match = re.search(r'filter:\s*(\S+)', line)
            if filter_match:
                newData["filter"] = filter_match.group(1)

            channels_match = re.search(r'channels:\s*([^\n}]+)', line)
            if channels_match:
                channels_str = channels_match.group(1).strip()
                newData["channels"] = channels_str.split(',')

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

    def process_single_file(self, file_path):
        self.log_file_name = file_path
        print('Log Processing: ', self.log_file_name)
        print('Start of CBL Log Reader: ', datetime.now())
        start = time.time()
        with open(file_path, "r") as log_file:
            seq = 1
            for line in log_file:
                line = line.rstrip('\r\n')
                if self.is_start_of_new_log_line(line):
                    self.bigLineProcecess(line, seq)
                    seq += 1
        end = time.time()
        print('End of CBL Log Reader  : ', datetime.now())
        print('Total Process Time(sec): ', end - start)
        print('Log Lines Processed    : ', seq - 1)

    def read_log(self):
        file_types = self.file_parse_type.split('|')
        error_message = (
            "There doesn't seem to be any known file names with info|error|debug|verbose|warning. "
            "If you want to process a single file, please specify it in config.json "
            '"file-to-parse": "/path/to/random.txt|log" that should have Couchbase Lite logs in text format'
        )

        if os.path.isfile(self.file_to_parse):
            # Check if it’s a .txt or .log file
            if self.file_to_parse.lower().endswith(('.txt', '.log')):
                # Check if the filename contains any known type
                filename = os.path.basename(self.file_to_parse).lower()
                if any(ft.lower() in filename for ft in file_types):
                    self.process_single_file(self.file_to_parse)
                else:
                    print(f"Error: {self.file_to_parse} does not match known log types ({self.file_parse_type})")
                    print(error_message)
                    exit()
            else:
                print(f"Error: {self.file_to_parse} is not a .txt or .log file")
                exit()
        elif os.path.isdir(self.file_to_parse):
            matching_files = []
            # Scan directory for matching files
            for filename in os.listdir(self.file_to_parse):
                full_path = os.path.join(self.file_to_parse, filename)
                if os.path.isfile(full_path) and filename.lower().endswith(('.txt', '.log')):
                    if any(ft.lower() in filename.lower() for ft in file_types):
                        matching_files.append(full_path)
            
            if not matching_files:
                print(f"No matching .txt or .log files found in {self.file_to_parse} with types {self.file_parse_type}")
                print(error_message)
                exit()
            
            # Process each matching file
            for file_path in matching_files:
                self.process_single_file(file_path)
        else:
            print(f"Error: {self.file_to_parse} is neither a valid file nor directory")
            exit()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        print("Error: No config file provided")
        exit()
    log_reader = LogReader(config_file)
    log_reader.read_log()