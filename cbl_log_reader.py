import sys
import subprocess
from pathlib import Path
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
    cluster = None
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
    cblName = []  # New instance variable to store CBL info
    autoStartDashboard = False 

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
            self.autoStartDashboard = config.get('auto-start-dashboard', False)

    def makeCB(self):
        try:
            auth = PasswordAuthenticator(self.cbUser, self.cbPass)
            self.cluster = Cluster('couchbase://' + self.cbHost, ClusterOptions(auth))
            self.cluster.wait_until_ready(timedelta(seconds=5))
            self.cb =self.cluster.bucket(self.cbBucketName)
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
            dt_str = full_date_match.group(1)
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))  # Parse ISO-8601
            return [dt_str, True, dt.timestamp()]  # Return float timestamp with microsecond precision

        time_only_pattern = r'^(\d{2}:\d{2}:\d{2}\.\d+)\|'
        time_only_match = re.search(time_only_pattern, log_line)
        if time_only_match:
            time_str = time_only_match.group(1)  # e.g., "11:30:45.123456"
            current_time = datetime.strptime(time_str, "%H:%M:%S.%f")

            # Use yesterday as base date (March 27, 2025, since today is March 28)
            base_date = datetime.now().date() - timedelta(days=1)
            
            # Check for day rollover by comparing with the last timestamp
            if not hasattr(self, 'last_time'):
                self.last_time = None
            
            if self.last_time and current_time < self.last_time:
                # Rollover detected (e.g., 23:59:59 -> 00:00:01), use today
                base_date = datetime.now().date()
            
            self.last_time = current_time
            
            # Combine base date and time into ISO-8601
            dt = datetime.combine(base_date, current_time.time())
            iso_date = dt.isoformat()
            epoch = dt.timestamp()  # Return float timestamp with microsecond precision
            return [iso_date, False, epoch]
        
        return [None, False, None]  # Return [dt, full_date_flag, epoch]
    '''

    def extract_timestamp(self, log_line):
        full_date_pattern = r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+(?:Z|[+-]\d{2}:\d{2})?)\|'
        full_date_match = re.search(full_date_pattern, log_line)
        if full_date_match:
            dt_str = full_date_match.group(1)
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return [dt_str, True, dt.timestamp()]

        time_only_pattern = r'^(\d{2}:\d{2}:\d{2}\.\d+)\|'
        time_only_match = re.search(time_only_pattern, log_line)
        if time_only_match:
            time_str = time_only_match.group(1)  # e.g., "17:24:02.456955"
            current_time = datetime.strptime(time_str, "%H:%M:%S.%f")
            # Use yesterday as base date for epoch calculation only
            base_date = datetime.now().date() - timedelta(days=1)
            
            if not hasattr(self, 'last_time'):
                self.last_time = None
            
            if self.last_time and current_time < self.last_time:
                base_date = datetime.now().date()  # Today if rollover
            
            self.last_time = current_time
            
            dt = datetime.combine(base_date, current_time.time())
            epoch = dt.timestamp()
            return [time_str, False, epoch]  # Return original time string, not ISO
        
        return [None, False, None]
    '''
    

    def find_error_in_line(self, line, is_full_date):
        if self.check_error_end_of_line(line):
            return False
        # Look for ERROR or ERR anywhere in the line
        if re.search(r'(ERROR|ERR)(?:\s|:|$)', line, re.IGNORECASE) or \
        re.search(r' (error|err) ', line, re.IGNORECASE):
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
            # Extract process ID
            pid_match = re.search(r'Sync\s*\{(\d+)\}', log_line) if '|' in log_line else re.search(r'\[Sync\]:\s*\{(\d+)\}', log_line)
            pid = int(pid_match.group(1)) if pid_match else None
            return [int(match.group(1)), float(match.group(2)), float(match.group(3)), pid]
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
        """
        Extracts sync configuration details from a log line and returns a list of collection dictionaries.

        Args:
            line (str): The log line containing the configuration string.

        Returns:
            list: A list of dictionaries, each containing 'coll', 'name', 'push', 'pull', and optionally 'channels'.
        """
        if self.debug: print(f"Input log line: {line[:100]}... (truncated)")

        # Find the start of the config section
        config_start = line.find('config: ')
        if config_start == -1:
            if self.debug: print("Error: No 'config: ' found in the log line.")
            return []
        config_start += len('config: ')
        if self.debug: print(f"Position after 'config: ': {config_start}")

        # Find the opening triple braces '{{{'
        brace_start = line.find('{{{', config_start)
        if brace_start == -1:
            if self.debug: print("Error: No '{{{' found after 'config: '.")
            return []
        #print(f"Position of '{{{': {brace_start}")

        # Use brace counting to find the closing '}}}'
        counter = 3  # Starting count for '{{{'
        i = brace_start + 3  # Start AFTER '{{{'
        if self.debug: print(f"Starting brace count at position {i}, counter = {counter}")
        while i < len(line) and counter > 0:
            if line[i] == '{':
                counter += 1
                if self.debug: print(f"Found '{{' at position {i}, counter = {counter}")
            elif line[i] == '}':
                counter -= 1
                if self.debug: print(f"Found '}}' at position {i}, counter = {counter}")
            i += 1

        if counter != 0:
            if self.debug: print("Error: Unmatched braces; cannot find closing '}}}'.")
            return []
        #print(f"Position after '}}}': {i}")

        # Extract the config string between '{{{' and '}}}'
        config_str = line[brace_start:i]  # Include full {{{...}}}
        if self.debug: print(f"Extracted config_str (full): {config_str[:100]}... (truncated)")
        config_str = config_str[3:-3]  # Strip {{{ and }}}
        if self.debug: print(f"Extracted config_str (stripped): {config_str[:100]}... (truncated)")

        # Parse collections from config_str
        collections = []
        # Updated pattern to match 'Coll#<number>}' instead of '{Coll#<number>}'
        coll_pattern = r'Coll#(\d+)\}\s*"([^"]+)":\s*\{((?:[^}{]+|\{[^}]*\})*)\}'
        matches = list(re.finditer(coll_pattern, config_str))
        if self.debug: print(f"Number of collection matches found: {len(matches)}")

        for match in matches:
            coll_id = int(match.group(1))
            coll_name = match.group(2)
            coll_options = match.group(3)
            if self.debug: print(f"\nProcessing Collection ID: {coll_id}, Name: '{coll_name}', Options: {coll_options[:50]}... (truncated)")

            coll_dict = {"coll": coll_id, "name": coll_name}

            push_match = re.search(r'"Push":\s*(\w+)', coll_options)
            if push_match:
                coll_dict["push"] = push_match.group(1)
                if self.debug: print(f"  Push setting: {coll_dict['push']}")
            else:
                if self.debug: print("  No Push setting found.")

            pull_match = re.search(r'"Pull":\s*(\w+)', coll_options)
            if pull_match:
                coll_dict["pull"] = pull_match.group(1)
                if self.debug: print(f"  Pull setting: {coll_dict['pull']}")
            else:
                if self.debug: print("  No Pull setting found.")

            channels_match = re.search(r'channels:\s*\[([^\]]+)\]', coll_options)
            if channels_match:
                channels_str = channels_match.group(1)
                channels = [ch.strip().strip('"') for ch in re.split(r',\s*', channels_str) if ch.strip()]
                coll_dict["channels"] = channels
                if self.debug: print(f"  Channels (first 5): {channels[:5]}... (total: {len(channels)})")
            else:
                if self.debug: print("  No channels found.")

            collections.append(coll_dict)

        if self.debug: print(f"\nFinal collections list: {collections}")
        return collections


    def extract_pids(self, line):
        """
        Extracts all process IDs from a log line in various formats.
        Returns a list of unique PIDs (integers or hex strings).
        """
        pids = set()  # Use a set to avoid duplicates

        # Pattern 1: {pid} or {pid|stuff-after}
        pid_brace_pattern = r'\{(\d+)(?:\|[^}]*)?\}'
        for match in re.finditer(pid_brace_pattern, line):
            pids.add(int(match.group(1)))

        # Pattern 2: Hex format like @0x1a2b3c
        pid_hex_pattern = r'@0x[0-9a-fA-F]+'
        for match in re.finditer(pid_hex_pattern, line):
            pids.add(match.group(0))  # Keep as string for hex values

        # Pattern 3: Component#pid (e.g., Pusher#123, Puller#456)
        component_pid_pattern = r'(?:Pusher|Puller|RevFinder|ChangesFeed|Repl)#(\d+)'
        for match in re.finditer(component_pid_pattern, line):
            pids.add(int(match.group(1)))

        # Convert set to sorted list
        return sorted(list(pids), key=str)  # Sort for consistency; handles mixed int/str


    def bigLineProcecess(self, line, seq):
        if self.debug:
            print(line)

        newData = {}
        newData["logLine"] = seq
        timestamp_result = self.extract_timestamp(line)
        newData["dt"] = timestamp_result[0]  # ISO-8601, fake or real
        newData["fullDate"] = timestamp_result[1]  # True if original ISO, False if fake
        newData["dtEpoch"] = timestamp_result[2]  # Unix timestamp (float) with microsecond precision
        base_type = self.find_type(line, timestamp_result[1])
        is_full_date = timestamp_result[1]

        # Extract PIDs upfront and store in newData
        newData["processId"] = self.extract_pids(line)

        ### Special Case: CouchbaseLite Version Info ###
        if "---- CouchbaseLite" in line:
            newData["type"] = "CBL:Info"
            version_match = re.search(r'CouchbaseLite\s+\S+\s+v([\d\.\-@]+)', line)
            type_match = re.search(r'\((EE|CE)/', line)
            platform_match = re.search(r'on\s+(\w+);\s+([^;]+)', line)
            
            cbl_info = {
                "cblVersion": version_match.group(1) if version_match else "Unknown",
                "cblType": type_match.group(1) if type_match else "Unknown",
                "platform": platform_match.group(1) if platform_match else "Unknown",
                "fileName": self.log_file_name
            }
            self.cblName.append(cbl_info)
            newData["cblVersion"] = cbl_info["cblVersion"]
            newData["cblType"] = cbl_info["cblType"]
            newData["platform"] = cbl_info["platform"]

        ### ERRORs ######
        else:
            if self.find_error_in_line(line, is_full_date):
                newData["error"] = True
                eType = line.split("ERROR: ")
                if line.find("SQLite error (code 14)") != -1:
                    newData["errorType"] = "SQLite error (code 14) [edit] Opening DB"
                else:
                    if len(eType) > 1:
                        newData["errorType"] = eType[1]

        newData["fileName"] = self.log_file_name

        # Dispatch to type-specific processors (only if not CBL:Info)
        if "type" not in newData:
            if base_type == "Sync":
                newData["mainType"] = "Sync"
                self.process_sync(line, is_full_date, newData)
            elif base_type == "WS":
                newData["mainType"] = "WS"
                self.process_ws(line, is_full_date, newData)
            elif base_type == "Query":
                newData["mainType"] = "Query"
                self.process_query(line, is_full_date, newData)
            elif base_type == "Changes":
                newData["mainType"] = "Changes"
                self.process_changes(line, is_full_date, newData)
            elif base_type == "BLIPMessages":
                newData["mainType"] = "BLIPMessages"
                self.process_blip_messages(line, is_full_date, newData)
            elif base_type == "BLIP":
                newData["mainType"] = "BLIP"
                self.process_blip(line, is_full_date, newData)
            elif base_type == "SQL":
                newData["mainType"] = "SQL"
                self.process_sql(line, is_full_date, newData)
            elif base_type == "DB":
                newData["mainType"] = "DB"
                self.process_db(line, is_full_date, newData)
            elif base_type == "Actor":
                newData["mainType"] = "Actor"
                self.process_actor(line, is_full_date, newData)
            elif base_type == "Zip":
                newData["mainType"] = "Zip"
                self.process_zip(line, is_full_date, newData)
            else:
                newData["mainType"] = "Other"
                if base_type:
                    newData["type"] = f"Other:{base_type}"
                else:
                    newData["type"] = "Other:Unknown"
                    if self.debug:
                        print(f"Warning: No base_type identified for line: {line}")

        newData["rawLog"] = line
        dict_string = json.dumps(newData, sort_keys=True)
        cbKey = uuid.uuid5(uuid.NAMESPACE_DNS, dict_string)
        self.cbUpsert(str(cbKey), newData, self.cbTtl)


    def process_actor(self, line, is_full_date, newData):
        newData["type"] = "Actor:Starting"
        # Extract scheduler details if needed
        scheduler_match = re.search(r'Scheduler<([^>]+)> with (\d+) threads', line)
        if scheduler_match:
            newData["schedulerId"] = scheduler_match.group(1)
            newData["threadCount"] = int(scheduler_match.group(2))


    def extract_endpoint(self,log_line):
        """
        Extracts endpoint information from a log line.
        Returns a dictionary with the endpoint type and value, or None if no endpoint is found.
        """
        # Patterns for different endpoint types
        url_pattern = r"endpoint:\s*(wss://[^\s}]+)"  # For wss:// URLs
        msg_pattern = r"endpoint:\s*(x-msg-endpt:///[^\s}]+)"  # For x-msg-endpt://
        url_endpoint_pattern = r"URLEndpoint\{url=(wss://[^\s}]+)"  # For URLEndpoint{url=...}
        msg_endpoint_pattern = r"MessageEndpoint\{([^}]+)}"  # For MessageEndpoint{...}

        # Try matching each pattern
        url_match = re.search(url_pattern, log_line)
        if url_match:
            return {
                "type": "url",
                "value": url_match.group(1)
            }

        msg_match = re.search(msg_pattern, log_line)
        if msg_match:
            return {
                "type": "message",
                "value": msg_match.group(1)
            }

        url_endpoint_match = re.search(url_endpoint_pattern, log_line)
        if url_endpoint_match:
            return {
                "type": "url",
                "value": url_endpoint_match.group(1)
            }

        msg_endpoint_match = re.search(msg_endpoint_pattern, log_line)
        if msg_endpoint_match:
            return {
                "type": "message",
                "value": msg_endpoint_match.group(1)
            }

        # Return None if no endpoint is found
        return None
    
    def check_and_convert(self,value):
        # Check if it's an integer
        if isinstance(value, int):
            if self.debug: print(f"{value} is an integer")
            return value
        # Check if it's a string
        elif isinstance(value, str):
            if self.debug: print(f"{value} is a string")
            try:
                # Try to convert string to integer
                converted = int(value)
                if self.debug: print(f"Converted {value} to integer: {converted}")
                return converted
            except ValueError:
                if self.debug: print(f"Cannot convert {value} to integer")
                return value  # Return original string if conversion fails
    
    def extract_endpoint_and_pid(self, log_line):
        pid_hex_pattern = r"@0x[0-9a-fA-F]+"
        pid_brace_pattern = r"\{([^|]+)\|"
        url_pattern = r"endpoint:\s*(wss?://[^\s}]+)"  # For ws:// and wss://
        msg_pattern = r"endpoint:\s*(x-msg-(?:endpt|conn)://([^\s}]+))"  # For x-msg-endpt:// and x-msg-conn://

        result = {}
        # Check for process ID
        pid_brace_match = re.search(pid_brace_pattern, log_line)
        if pid_brace_match:
            result["process_id"] = self.check_and_convert(pid_brace_match.group(1))
        else:
            pid_hex_match = re.search(pid_hex_pattern, log_line)
            if pid_hex_match:
                result["process_id"] = self.check_and_convert(pid_hex_match.group(0))
        
        # Check for URL (ws:// or wss://)
        url_match = re.search(url_pattern, log_line)
        if url_match:
            result["type"] = "url"
            result["value"] = url_match.group(1)  # Full URL
        else:
            # Check for message endpoint (x-msg-endpt:// or x-msg-conn://)
            msg_match = re.search(msg_pattern, log_line)
            if msg_match:
                result["type"] = "message"
                result["value"] = msg_match.group(2)  # Path after the protocol
        
        return result if result else None


    def process_sync(self, line, is_full_date, newData):
        # No need to initialize processId here; it's already done in bigLineProcecess
        if "collection" not in newData:
            newData["collection"] = []
        if "correlationId" not in newData:
            newData["correlationId"] = []

        ##### Extract endpoint information (PID already handled)
        info = self.extract_endpoint_and_pid(line)
        if info and "type" in info and "value" in info:
            newData["endpoint"] = {"type": info["type"], "value": info["value"]}

        ###### Sync Start ######
        if 'Starting Replicator' in line and 'config:' in line:
            newData["type"] = "Sync:Start"
            newData["replicationConfig"] = self.getSyncConfig(line)
            # PID already captured by extract_pids

        ###### State Changes ######
        elif '[JAVA] State changed' in line:
            newData["type"] = "Sync:StateChange"
            # PID already captured by extract_pids

        ###### Status Changes ######
        elif '[JAVA] status changed' in line:
            newData["type"] = "Sync:Status"
            # PID already captured by extract_pids

        ###### Rejection of Proposed Changes ######
        elif 'Rejecting proposed change' in line:
            newData["type"] = "Sync:Rejection"
            # PID already captured by extract_pids

        ###### Conflict Check ######
        elif ('Found' in line and 'conflicted docs' in line) or 'Scanning for pre-existing conflicts' in line:
            newData["type"] = "Sync:ConflictCheck"
            # PID already captured by extract_pids

        ###### Checkpoint ######
        elif 'checkpoint' in line.lower():
            newData["type"] = "Sync:Checkpoint"
            # PID already captured by extract_pids

        ###### Revocation ######
        elif 'msg["revocations"]' in line:
            newData["type"] = "Sync:Revocation"
            # PID already captured by extract_pids

        ###### Starting Pull or Push ######
        elif 'Starting pull from remote seq' in line or 'Starting continuous push from local seq' in line:
            newData["type"] = "Sync:Starting"
            coll_match = re.search(r'Coll=(\d+)', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)
            seq_match = re.search(r"seq (?:'([^']*)'|#(\d+))", line)
            if seq_match:
                newData["remoteSeq"] = seq_match.group(1) if seq_match.group(1) else seq_match.group(2)

        ###### Changes Received or Responded ######
        elif ('Received' in line and 'changes' in line and 'seq' in line) or "Responded to 'changes'" in line or 'No new observed changes' in line:
            newData["type"] = "Sync:Changes"
            coll_match = re.search(r'Coll=(\d+)', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)
            changes_match = re.search(r'Received (\d+) changes', line)
            if changes_match:
                newData["changesCount"] = int(changes_match.group(1))
            seq_match = re.search(r"seq '([^']+)'..'([^']+)'", line)
            if seq_match:
                newData["remoteSeq"] = f"{seq_match.group(1)}..{seq_match.group(2)}"
            revs_match = re.search(r'request for (\d+) revs in ([\d.]+) sec', line)
            if revs_match:
                newData["changesRevs"] = int(revs_match.group(1))
                newData["responseTimeSec"] = float(revs_match.group(2))

        ###### Caught Up ######
        elif 'Caught up with remote changes' in line or 'Caught up, at lastSequence' in line:
            newData["type"] = "Sync:CaughtUp"
            coll_match = re.search(r'Coll=(\d+)', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)
            seq_match = re.search(r'lastSequence #(\d+)', line)
            if seq_match:
                newData["lastSequence"] = int(seq_match.group(1))

        ###### Replication Complete ######
        elif 'Replication complete!' in line:
            newData["type"] = "Sync:Complete"
            # PID already captured by extract_pids

        ###### Connection Closed ######
        elif 'Connection closed with WebSocket/HTTP status' in line:
            newData["type"] = "Sync:Closed"
            coll_match = re.search(r'Coll=(\d+)', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)
            corr_id_match = re.search(r'CorrID=([a-f0-9]+)', line)
            if corr_id_match:
                corr_id = corr_id_match.group(1)
                if corr_id not in newData["correlationId"]:
                    newData["correlationId"].append(corr_id)
            status_match = re.search(r'status (\d+)', line)
            if status_match:
                newData["ConnectionStatus"] = int(status_match.group(1))

        ###### Connected ######
        elif 'Connected!' in line:
            newData["type"] = "Sync:Connected"
            coll_match = re.search(r'Coll=(\d+)', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)
            corr_id_match = re.search(r'CorrID=([a-f0-9]+)', line)
            if corr_id_match:
                corr_id = corr_id_match.group(1)
                if corr_id not in newData["correlationId"]:
                    newData["correlationId"].append(corr_id)

        ###### Stopped ######
        elif 'Told to stop!' in line:
            newData["type"] = "Sync:Stopped"
            coll_match = re.search(r'Coll=(\d+)', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)
            corr_id_match = re.search(r'CorrID=([a-f0-9]+)', line)
            if corr_id_match:
                corr_id = corr_id_match.group(1)
                if corr_id not in newData["correlationId"]:
                    newData["correlationId"].append(corr_id)

        ###### Other Sync Lines ######
        else:
            repl_ids_match = re.search(r'Sync\s*\{(?:\d+\|)?([^}]+)\}', line) if is_full_date else re.search(r'\[Sync\]:\s*\{(?:\d+\|)?([^}]+)\}', line)
            single_id_match = re.search(r'Sync\s*\{(\d+)\}', line) if is_full_date else re.search(r'\[Sync\]:\s*\{(\d+)\}', line)
            
            if single_id_match and "State:" in line:
                newData["type"] = "Sync:State"
            elif repl_ids_match:
                newData["type"] = "Sync:Other"
                repl_ids_dict = {}
                path = repl_ids_match.group(1)
                path_ids = re.findall(r'(C4RemoteRepl|Repl|Pusher|Puller|RevFinder)#(\d+)', path)
                for name, id_value in path_ids:
                    repl_ids_dict[name] = int(id_value)
                if repl_ids_dict:
                    newData["replicationIds"] = repl_ids_dict

            coll_match = re.search(r'\{Coll#(\d+)\}', line)
            if coll_match:
                coll_id = int(coll_match.group(1))
                if coll_id not in newData["collection"]:
                    newData["collection"].append(coll_id)

            received_changes_match = re.search(r'Received\s+(\d+)\s+changes', line)
            if received_changes_match:
                newData["receivedChanges"] = int(received_changes_match.group(1))

        # These checks can override type if they match

        repActiveStats = self.replication_status_stats(line)
        if repActiveStats:
            newData["type"] = "Sync:Active"
            newData["replicatorStatus"] = repActiveStats

        repClassStats = self.replicator_class_status(line)
        if repClassStats:
            newData["type"] = "Sync:Status"
            newData["replicatorClassStatus"] = repClassStats

        # Sync:Commit section
        sCs = self.sync_commit_stats_get(line)
        if sCs:
            newData["type"] = "Sync:Commit"
            newData["syncCommitStats"] = {
                "numInserts": sCs[0],
                "insertPerSec": sCs[2],
                "insertTime_ms": sCs[1],
                "avgPerInsert_ms": round(sCs[1] / sCs[0], 3) if sCs[0] > 0 else 0
            }

    def process_zip(self, line, is_full_date, newData):
        newData["type"] = "Zip:Copying"
        copy_match = re.search(r'Copying (\d+) bytes into (\d+)-byte buf', line)
        if copy_match:
            newData["bytesCopied"] = int(copy_match.group(1))
            newData["bufferSize"] = int(copy_match.group(2))
        repl_id_match = re.search(r'\{(\d+)\}', line)
        if repl_id_match:
            newData["replicationId"] = int(repl_id_match.group(1))

    def process_ws(self, line, is_full_date, newData):
        newData["type"] = "WS"
        if "WebSocket CLOSED with error" in line:
            newData["wsEvent"] = "CLOSED"
            newData["error"] = True
            error_start = line.find("java.net.UnknownHostException")
            if error_start != -1:
                newData["errorMessage"] = line[error_start:].strip()

    def process_query(self, line, is_full_date, newData):
        newData["type"] = "Query"
        a = self.find_pattern_query_line_1(line, is_full_date)
        if a:
            b = line.split(" --> ")
            newData["queryInfo"] = json.loads(b[1])

        queryExeStats = self.extract_query_info(line)
        if queryExeStats:
            newData["queryExeStats"] = queryExeStats

    def process_changes(self, line, is_full_date, newData):
        newData["type"] = "Changes"
        repl_id_match = re.search(r'Changes\s*\{(\d+)(?:\|)?', line) if is_full_date else re.search(r'\[Changes\]:\s*\{(\d+)(?:\|)?', line)
        if repl_id_match:
            newData["replicationId"] = int(repl_id_match.group(1))

    def process_blip(self, line, is_full_date, newData):
        newData["type"] = "BLIP"
        
        # Extract replication ID (e.g., {2288})
        repl_id_match = re.search(r'\{(\d+)\}', line)
        if repl_id_match:
            newData["replicationId"] = int(repl_id_match.group(1))

        # Check for specific BLIP events
        if "Closed with Network error" in line:
            newData["blipEvent"] = "Closed"
            newData["error"] = True
            # Extract error code and message
            error_match = re.search(r'error (\d+): (.+)$', line)
            if error_match:
                newData["errorCode"] = int(error_match.group(1))
                newData["errorMessage"] = error_match.group(2).strip()

        # Add more BLIP-specific parsing as needed
        # Example: if "Opened" or other states appear in your logs, add conditions here

    def process_blip_messages(self, line, is_full_date, newData):
        type_match = re.search(r'BLIPMessages\s*(\w+):', line) if is_full_date else re.search(r'\[BLIPMessages\]:\s*(\w+):', line)
        if type_match and type_match.group(1) in ("SENDING", "RECEIVED"):
            newData["type"] = f"BLIPMessages:{type_match.group(1)}"
        else:
            newData["type"] = "BLIPMessages:Unknown"

        repl_id_match = re.search(r'REQ #(\d+)', line) or re.search(r'RES #(\d+)', line)
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

        if "filter: sync_gateway/bychannel" in line:
            channels_match = re.search(r'channels:\s*([^\n}]+)', line)
            if channels_match:
                channels_str = channels_match.group(1).strip()
                newData["channels"] = [ch.strip() for ch in channels_str.split(',') if ch.strip()]

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


    def process_sql(self, line, is_full_date, newData):
        # Default type
        newData["type"] = "SQL:Unknown"

        # Check for specific SQL operations
        if "SELECT" in line:
            newData["type"] = "SQL:SELECT"
            # Optionally extract the SELECT query details
            query_match = re.search(r'SELECT\s+(.+?)(?:\s+FROM|$)', line, re.IGNORECASE)
            if query_match:
                newData["sqlQuery"] = query_match.group(0).strip()
        elif "CREATE" in line:
            newData["type"] = "SQL:CREATE"
            # Optionally extract table name and details
            table_match = re.search(r'CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([^"\s]+)"?', line, re.IGNORECASE)
            if table_match:
                newData["tableName"] = table_match.group(1)
        elif "INSERT" in line:
            newData["type"] = "SQL:INSERT"
        elif "UPDATE" in line:
            newData["type"] = "SQL:UPDATE"
        elif "DELETE" in line:
            newData["type"] = "SQL:DELETE"
        elif "COMMIT" in line:
            newData["type"] = "SQL:COMMIT"
        elif "BEGIN" in line:
            newData["type"] = "SQL:BEGIN"
        elif "SAVEPOINT" in line:
            newData["type"] = "SQL:SAVEPOINT"

        # Store the full SQL statement if desired
        sql_start = line.find("[SQL]:") + 6 if is_full_date else line.find("[SQL]:") + 6
        newData["sqlStatement"] = line[sql_start:].strip()

    def process_db(self, line, is_full_date, newData):
        newData["type"] = "DB:Collection"

        # Extract collection number (e.g., 8 from Collection#8)
        collection_match = re.search(r'Collection#(\d+)', line)
        if collection_match:
            newData["collection"] = int(collection_match.group(1))

        # Extract DB number (e.g., 5 from DB#5)
        db_match = re.search(r'DB#(\d+)', line)
        if db_match:
            newData["dbNumber"] = int(db_match.group(1))

        # Check for specific DB events (e.g., "Instantiated")
        if "Instantiated" in line:
            newData["dbEvent"] = "Instantiated"


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

    def generate_report(self):
        report = {
            "logDtOldest": None,
            "logDtNewest": None,
            "types": [],
            "errorStatus": [],
            "replicationStats": [],
            "fakeDates": False,  # Default to False
            "cblInfo": self.cblName  # Add cblName info here
        }

        print("Making Report - Doc ID: `log_report`")

        try:
            # Query for oldest and newest timestamps
            timestamp_query = """
                SELECT MIN(cbl.dt) AS oldest, MAX(cbl.dt) AS newest,
                    MAX(cbl.fullDate) AS hasFullDate
                FROM `cbl-log-reader` AS cbl
                WHERE cbl.dt IS NOT MISSING
            """
            timestamp_result = self.cluster.query(timestamp_query, QueryOptions(timeout=timedelta(seconds=75)))
            for row in timestamp_result:
                if self.debug:
                    print(f"Timestamp query result: {row}")
                report["logDtOldest"] = row["oldest"]
                report["logDtNewest"] = row["newest"]
                report["fakeDates"] = not row["hasFullDate"]  # True if no full ISO dates

            # Query for type counts
            type_query = """
                SELECT COUNT(cbl.`type`) AS typeCount, cbl.`type`
                FROM `cbl-log-reader` AS cbl
                WHERE cbl.dt IS NOT MISSING 
                AND cbl.`type` IS NOT MISSINg
                GROUP BY cbl.`type`
                ORDER BY cbl.`type`
            """
            type_result = self.cluster.query(type_query, QueryOptions(timeout=timedelta(seconds=75)))
            type_rows = list(type_result)
            if self.debug:
                print(f"Type query result: {type_rows}")
            if not type_rows and self.debug:
                print("Warning: No type counts found. Check if 'type' field is populated in documents.")
            report["types"] = [{"type": row["type"], "typeCount": row["typeCount"]} for row in type_rows]

            # Query for error counts
            error_query = """
                SELECT COUNT(cbl.`type`) AS errorCount, cbl.`type`
                FROM `cbl-log-reader` AS cbl
                WHERE 
                cbl.dt IS NOT MISSING 
                AND cbl.`error` = True 
                AND cbl.`type` IS NOT MISSING
                GROUP BY cbl.`type`
                ORDER BY cbl.`type`
            """

            if self.debug:
                print(f"Error query: {error_query}")

            error_result = self.cluster.query(error_query, QueryOptions(timeout=timedelta(seconds=75)))
            error_rows = list(error_result)
            if self.debug:
                print(f"Error query result: {error_rows}")
            report["errorStatus"] = [{"type": row["type"], "errorCount": row["errorCount"]} for row in error_rows]

            # Query for replication stats with start time
            replication_query = """
                                SELECT bigHug.*
                                FROM (
                                    SELECT pid1 AS replicationId,
                                        COUNT(*) AS totalCount,
                                        SUM(CASE WHEN cbl.type = 'Sync:Rejection' THEN 1 ELSE 0 END) AS rejectionCount,
                                        SUM(COALESCE(cbl.syncCommitStats.numInserts, 0)) + SUM(COALESCE(cbl.replicatorStatus.docs, 0)) AS documentCount,
                                        MIN(cbl.dt) AS startTime
                                    FROM `cbl-log-reader` AS cbl
                                    UNNEST cbl.processId AS pid1
                                    WHERE cbl.dt IS NOT MISSING
                                        AND cbl.type IS NOT MISSING
                                        AND cbl.processId IS NOT NULL
                                        AND SPLIT(cbl.`type`, ':')[0] = 'Sync'
                                    GROUP BY pid1 ) AS bigHug
                                WHERE bigHug.documentCount > 0
                                    OR bigHug.rejectionCount > 0
                                ORDER BY startTime
                                """
            if self.debug:
                print(f"Replication query: {replication_query}")
            
            replication_result = self.cluster.query(replication_query, QueryOptions(timeout=timedelta(seconds=10)))
            replication_rows = list(replication_result)
            if self.debug:
                print(f"Replication query result: {replication_rows}")
            

            # Sort by startTime and build replicationStats
            replication_stats = [{
                    "replicationProcessId": row["replicationId"],
                    "totalLogEntries": row["totalCount"],
                    "localWriteRejectionCount": row["rejectionCount"],
                    "documentsProcessedCount": row["documentCount"],
                    "startTime": row["startTime"],
                    "endpoint":  row.get("endpoint", None) 
                } for row in replication_rows
            ]
            report["replicationStats"] = replication_stats

            replication_start_query = """
                            SELECT cbl.dt ,
                                cbl.`endpoint`,
                                cbl.processId,
                                ARRAY_COUNT(cbl.replicationConfig) as collectionCount
                            FROM `cbl-log-reader` AS cbl
                            WHERE cbl.dt IS NOT MISSING
                                AND cbl.processId IS NOT NULL
                                AND cbl.`endpoint` IS NOT MISSING
                                AND cbl.`type` = 'Sync:Start'
                                ORDER by cbl.dt
                                """
            if self.debug:
                print(f"Replication start query result: {replication_start_query}")
            replication_starts_result = self.cluster.query(replication_start_query, QueryOptions(timeout=timedelta(seconds=10)))
            replication_starts_rows = list(replication_starts_result)
            if self.debug:
                print(f"Replication starts query result: {replication_starts_rows}")

            replication_starts = [{
                    "collectionCount": row["collectionCount"],
                    "processId": row["processId"],
                    "startTime": row["dt"],
                    "endpoint":  row.get("endpoint", None) 
                    } for row in replication_starts_rows
            ] 
            report["replicationStarts"] = replication_starts


            # Upsert the report document
            report_key = "log_report"
            self.cbUpsert(report_key, report, self.cbTtl)
            if self.debug:
                print(f"Generated report document with key: {report_key}")

        except CouchbaseException as e:
            print(f"Failed to generate report: {e}")
        except KeyError as ke:
            print(f"KeyError in report generation: {ke}")


    def read_log(self):
        file_types = self.file_parse_type.split('|')
        error_message = (
            "There doesn't seem to be any known file names with info|error|debug|verbose|warning. "
            "If you want to process a single file, please specify it in config.json "
            '"file-to-parse": "/path/to/random.txt|log" that should have Couchbase Lite logs in text format'
        )

        if os.path.isfile(self.file_to_parse):
            if self.file_to_parse.lower().endswith(('.txt', '.log')):
                filename = os.path.basename(self.file_to_parse).lower()
                if any(ft.lower() in filename for ft in file_types):
                    self.process_single_file(self.file_to_parse)
                    self.generate_report()
                else:
                    print(f"Error: {self.file_to_parse} does not match known log types ({self.file_parse_type})")
                    print(error_message)
                    exit()
            else:
                print(f"Error: {self.file_to_parse} is not a .txt or .log file")
                exit()
        elif os.path.isdir(self.file_to_parse):
            matching_files = []
            for filename in os.listdir(self.file_to_parse):
                full_path = os.path.join(self.file_to_parse, filename)
                if os.path.isfile(full_path) and filename.lower().endswith(('.txt', '.log')):
                    if any(ft.lower() in filename.lower() for ft in file_types):
                        matching_files.append(full_path)
            
            if not matching_files:
                print(f"No matching .txt or .log files found in {self.file_to_parse} with types {self.file_parse_type}")
                print(error_message)
                exit()
            
            print(f"Total files to process: {len(matching_files)}")
            for file_idx, file_path in enumerate(matching_files, 1):
                print(f"Processing file {file_idx}/{len(matching_files)}: {file_path}")
                self.process_multi_line_file(file_path)
            self.generate_report()
        else:
            print(f"Error: {self.file_to_parse} is neither a valid file nor directory")
            exit()

        # Post-script report message
        report_message = """
        Report Generated:
        A report document has been created in Couchbase under the key 'log_report' in the 'cbl-log-reader' bucket.
        - What it does: This report summarizes key metrics from your Couchbase Lite log files.
        - What it analyzes:
        * 'logDtOldest' and 'logDtNewest': The earliest and latest timestamps in the logs, showing the time range covered.
        * 'types': Counts of each log type (e.g., 'Sync:State', 'BLIPMessages:SENDING'), showing activity distribution.
        * 'errorStatus': Counts of errors by log type, highlighting where issues occurred.
        * 'replicationStats': Details on replication processes, including:
            - 'replicationProcessId': Unique ID of each replicator.
            - 'totalLogEntries': Number of log lines for that replicator.
            - 'localWriteRejectionCount': Number of local write rejections (failed sync attempts).
            - 'documentsProcessedCount': Total documents processed (inserted or tracked).
            - 'startTime': When the replicator first appeared in the logs (sorted chronologically).
        - How to understand it:
        * Check 'replicationStats' for replication health—high 'localWriteRejectionCount' vs. 'documentsProcessedCount' indicates sync issues.
        * Use 'types' and 'errorStatus' to spot frequent or error-prone log categories.
        * Query it in Couchbase with: SELECT * FROM `cbl-log-reader` USE KEYS('log_report')
        """
        print(report_message)


    def process_multi_line_file(self, file_path):
        self.log_file_name = file_path
        print('Log Processing: ', self.log_file_name)
        print('Start of CBL Log Reader: ', datetime.now())
        start = time.time()

        # Count total lines in the file
        with open(file_path, "r") as log_file:
            total_lines = sum(1 for _ in log_file)
        if total_lines == 0:
            print("File is empty, skipping.")
            return

        bar_width = 20
        processed_lines = 0
        seq = 1
        current_log_entry = ""
        last_update_time = start  # For rate calculation

        with open(file_path, "r") as log_file:
            for line in log_file:
                processed_lines += 1
                line = line.rstrip('\r\n')
                if self.is_start_of_new_log_line(line):
                    if current_log_entry:
                        self.bigLineProcecess(current_log_entry, seq)
                        seq += 1
                    current_log_entry = line
                else:
                    current_log_entry += " " + line.strip()

                # Update progress bar and ETA every 100 lines or at the end
                if processed_lines % 100 == 0 or processed_lines == total_lines:
                    current_time = time.time()
                    elapsed = current_time - start
                    if elapsed > 0:  # Avoid division by zero
                        rate = processed_lines / elapsed  # Lines per second
                        remaining_lines = total_lines - processed_lines
                        eta_seconds = remaining_lines / rate if rate > 0 else 0
                        if eta_seconds > 60:
                            eta_display = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                        else:
                            eta_display = f"{eta_seconds:.1f}s"
                    else:
                        eta_display = "Calculating..."

                    progress = processed_lines / total_lines
                    filled = int(bar_width * progress)
                    bar = '#' * filled + '-' * (bar_width - filled)
                    percent = progress * 100
                    print(f"\rProgress: [{bar}] {percent:.1f}% ({processed_lines}/{total_lines} lines) | ETA: {eta_display}", end='', flush=True)

            if current_log_entry:
                self.bigLineProcecess(current_log_entry, seq)
                seq += 1

        # Final progress update
        end = time.time()
        elapsed = end - start
        print(f"\rProgress: [{'#' * bar_width}] 100.0% ({total_lines}/{total_lines} lines) | ETA: 0s", flush=True)
        print('End of CBL Log Reader  : ', datetime.now())
        print('Total Process Time(sec): ', elapsed)
        print('Log Lines Processed    : ', seq - 1)

    def process_single_file(self, file_path):
        self.log_file_name = file_path
        print('Log Processing: ', self.log_file_name)
        print('Start of CBL Log Reader: ', datetime.now())
        start = time.time()

        with open(file_path, "r") as log_file:
            total_lines = sum(1 for _ in log_file)
        if total_lines == 0:
            print("File is empty, skipping.")
            return

        bar_width = 20
        processed_lines = 0
        seq = 1

        with open(file_path, "r") as log_file:
            for line in log_file:
                processed_lines += 1
                self.bigLineProcecess(line.rstrip('\r\n'), seq)
                seq += 1

                # Update progress bar and ETA every 100 lines or at the end
                if processed_lines % 100 == 0 or processed_lines == total_lines:
                    current_time = time.time()
                    elapsed = current_time - start
                    if elapsed > 0:
                        rate = processed_lines / elapsed
                        remaining_lines = total_lines - processed_lines
                        eta_seconds = remaining_lines / rate if rate > 0 else 0
                        if eta_seconds > 60:
                            eta_display = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                        else:
                            eta_display = f"{eta_seconds:.1f}s"
                    else:
                        eta_display = "Calculating..."

                    progress = processed_lines / total_lines
                    filled = int(bar_width * progress)
                    bar = '#' * filled + '-' * (bar_width - filled)
                    percent = progress * 100
                    print(f"\rProgress: [{bar}] {percent:.1f}% ({processed_lines}/{total_lines} lines) | ETA: {eta_display}", end='', flush=True)

        end = time.time()
        elapsed = end - start
        print(f"\rProgress: [{'#' * bar_width}] 100.0% ({total_lines}/{total_lines} lines) | ETA: 0s", flush=True)
        print('End of CBL Log Reader  : ', datetime.now())
        print('Total Process Time(sec): ', elapsed)
        print('Log Lines Processed    : ', seq - 1)

    def start_web_server(self):
        """Start the web server if autoStartDashboard is true."""
        if self.autoStartDashboard:
            app_path = Path("app.py")
            config_path = Path(sys.argv[1])  # Assumes config.json is passed as arg
            if not app_path.exists():
                print("Error: app.py not found in current directory.")
                return
            if not config_path.exists():
                print(f"Error: Config file {config_path} not found.")
                return
            
            print("Starting web server: python3 app.py config.json")
            # Run the web server in a separate process
            subprocess.Popen(["python3", str(app_path), str(config_path)], cwd=Path.cwd())
            print("Web server started.")
            print("To stop the web server, press Ctrl+C")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        print("Error: No config.json file provided")
        print("# python3 cbl_log_reader.py config.json")
        exit()
    log_reader = LogReader(config_file)
    log_reader.read_log()
    #log_reader.generate_report()
    log_reader.start_web_server()