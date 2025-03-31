from flask import Flask, render_template, jsonify, request
import traceback
from couchbase.cluster import Cluster, ClusterOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import CouchbaseException, DocumentNotFoundException
import json
import sys
import hashlib

print("Starting app.py from /Users/fujio.turner/Documents/demo/cbl-log-reader/cbl-log-reader/")

DEBUG = False
app = Flask(__name__)

# Load configuration
if len(sys.argv) < 2:
    print("Error: Please provide config.json as an argument (e.g., python3 app.py config.json)")
    exit(1)

config_file = sys.argv[1]
try:
    with open(config_file) as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: Config file '{config_file}' not found.")
    exit(1)
except json.JSONDecodeError:
    print(f"Error: '{config_file}' is not a valid JSON file.")
    exit(1)

if config.get('debug') == True:
    DEBUG = True

required_keys = ['cb-cluster-host', 'cb-bucket-user', 'cb-bucket-user-password', 'cb-bucket-name']
missing_keys = [key for key in required_keys if key not in config]
if missing_keys:
    if DEBUG: print(f"Error: Missing required configuration keys in {config_file}: {missing_keys}")
    exit(1)

try:
    cluster = Cluster(f"couchbase://{config['cb-cluster-host']}", 
                      ClusterOptions(PasswordAuthenticator(config['cb-bucket-user'], config['cb-bucket-user-password'])))
    bucket = cluster.bucket(config['cb-bucket-name'])
    collection = bucket.default_collection()
    cbCacheBucket = cluster.bucket("cache")
    cbCache = cbCacheBucket.default_collection()
except Exception as e:
    if DEBUG: print(f"Error connecting to Couchbase cluster: {e}")
    exit(1)

def escape_fts_query_string(search_term):
    escaped_term = ''
    for char in search_term:
        if char == '*':
            escaped_term += '\\*'
        elif char == '/':
            escaped_term += '\\/'
        else:
            escaped_term += char
    return escaped_term

def escape_search_term(search_term):
    fts_escaped = escape_fts_query_string(search_term)
    n1ql_escaped = fts_escaped.replace('\\', '\\\\').replace("'", "''")
    return n1ql_escaped

def build_fts_query(search_term, field_name):
    """
    Build a Full-Text Search query string for Couchbase N1QL SEARCH() function.
    
    Args:
        search_term (str): The raw search term from the user (e.g., "ws:// AND endpoint*").
        field_name (str): The field to search (e.g., "rawLog").
    
    Returns:
        str: A properly formatted FTS query string for direct embedding.
    """
    # Escape forward slashes for FTS syntax
    escaped_term = search_term.replace('/', '\\/')
    # Escape single quotes for N1QL to prevent SQL injection
    n1ql_escaped_term = escaped_term.replace("'", "''")
    return n1ql_escaped_term

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_date_range', methods=['GET'])
def get_date_range():
    query = """
        SELECT MIN(dt) AS min_dt, MAX(dt) AS max_dt
        FROM `cbl-log-reader`
        WHERE dt IS NOT MISSING AND dt IS NOT NULL
    """
    cache_key = hashlib.md5(query.encode('utf-8')).hexdigest()
    if DEBUG: print(f"Generated cache key: {cache_key}")
    try:
        print("Cache hit for key:", cache_key)
        cached_result = cbCache.get(cache_key).value
        if DEBUG: print(f"Cache hit for key: {cache_key}")
        return jsonify(cached_result)
    except DocumentNotFoundException:
        if DEBUG: print(f"Cache miss for DocId: {cache_key}")
        try:
            result = cluster.query(query)
            for row in result:
                min_dt = row['min_dt']
                max_dt = row['max_dt']
                if DEBUG: print(f"Actual date range from database: min_dt={min_dt}, max_dt={max_dt}")
                data = {'start_date': min_dt[:10], 'end_date': max_dt[:10]}
                cbCache.upsert(cache_key, data)
                return jsonify(data)
        except CouchbaseException:
            if DEBUG: print(traceback.format_exc())
            return jsonify({'start_date': '2023-01-01', 'end_date': '2023-12-31'}), 500
        except Exception as e:
            if DEBUG: print(f"Error fetching date range: {e}")
            return jsonify({'start_date': '2023-01-01', 'end_date': '2023-12-31'}), 500
    except CouchbaseException:
        if DEBUG: print(traceback.format_exc())
        return jsonify({'start_date': '2023-01-01', 'end_date': '2023-12-31'}), 500
    except Exception as e:
        if DEBUG: print(f"Error accessing cache: {e}")
        return jsonify({'start_date': '2023-01-01', 'end_date': '2023-12-31'}), 500

@app.route('/get_types', methods=['GET'])
def get_types():
    query = """
        SELECT DISTINCT type
        FROM `cbl-log-reader`
        WHERE type IS NOT NULL
        ORDER BY type
    """
    maybe = hashlib.md5(query.encode('utf-8')).hexdigest()
    try:
        print("Cache hit for key:", maybe)
        y = cbCache.get(maybe).value
        return jsonify(y)
    except DocumentNotFoundException:
        if DEBUG: print("Cache miss for DocId:", maybe)
        try:
            result = cluster.query(query)
            types = [row['type'] for row in result]
            cbCache.upsert(maybe, types)
            return jsonify(types)
        except CouchbaseException:
            if DEBUG: print(traceback.format_exc())
            return jsonify([]), 500
        except Exception as e:
            if DEBUG: print(f"Error fetching types: {e}")
            return jsonify([]), 500
    except CouchbaseException:
        if DEBUG: print(traceback.format_exc())
        return jsonify([]), 500
    except Exception as e:
        if DEBUG: print(f"Error GET `log_report doc: {e}")
        return jsonify([]), 500

@app.route('/get_chart_data', methods=['POST'])
def get_chart_data():
    print("Endpoint /get_chart_data hit!")
    filters = request.get_json()
    if DEBUG: print(f"Request payload for /get_chart_data: {filters}")

    use_specific_type = filters.get('use_specific_type', False)
    grouping_mode = filters.get('grouping_mode', 'by-second')
    error_filter = filters.get('error_filter', False)
    types = filters.get('types', [])
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')

    if DEBUG: print(f"Filter parameters - use_specific_type: {use_specific_type}")
    if DEBUG: print(f"Filter parameters - grouping_mode: {grouping_mode}")
    if DEBUG: print(f"Filter parameters - error_filter: {error_filter}")
    if DEBUG: print(f"Filter parameters - types: {types}")
    if DEBUG: print(f"Filter parameters - search_term: {search_term}")

    type_field = "type" if use_specific_type else "SPLIT(type, ':')[0]"
    if DEBUG: print(f"Type field determined: {type_field}")

    where_clauses = ["dt IS NOT MISSING"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') <= $end_date")
    where_clauses.extend(["type IS NOT NULL", "dt IS NOT NULL"])
    
    query_params = {}
    if start_date and end_date:
        query_params = {'start_date': start_date, 'end_date': end_date}

    if search_term:
        fts_query_str = build_fts_query(search_term, "rawLog")
        if DEBUG:
            print("NEW: ", fts_query_str, " | ", search_term, "\n")
        where_clauses.append(f"SEARCH(`cbl-log-reader`, '{fts_query_str}')")
        # Do not add to query_params

    if DEBUG: print(f"Where clauses after date range and search: {where_clauses}")

    type_where_clause = "TRUE"
    if types:
        type_values = [f"'{t}'" for t in types]
        type_where_clause = f"{type_field} IN [{', '.join(type_values)}]"
    if DEBUG: print(f"Type where clause: {type_where_clause}")

    group_by_clause = "SUBSTR(dt, 0, 19)"
    if grouping_mode == "by-minute":
        group_by_clause = "SUBSTR(dt, 0, 16)"

    main_query = f"""
            SELECT REPLACE({group_by_clause}, 'T', ' ') AS second, {type_field} AS type, COUNT(*) AS count
            FROM `{config['cb-bucket-name']}`
            WHERE {' AND '.join(where_clauses)}
            GROUP BY REPLACE({group_by_clause}, 'T', ' '), {type_field}
    """

    if DEBUG: print(f"Main query constructed: {main_query}")

    error_query = f"""
                SELECT REPLACE({group_by_clause}, 'T', ' ') AS second, 'Error' AS type, COUNT(*) AS count
                FROM `{config['cb-bucket-name']}`
                WHERE {' AND '.join(where_clauses)} AND error = True
                GROUP BY REPLACE({group_by_clause}, 'T', ' ')
    """
    if DEBUG: print(f"Error query constructed: {error_query}")

    final_query = f"""
            SELECT combined.second, combined.type, combined.count
            FROM (
                {main_query}
                {'UNION ALL' if error_filter else ''}
                {error_query if error_filter else ''}
            ) AS combined
            ORDER BY combined.second
    """
    if DEBUG: print(f"Final query: {final_query}")

    params_str = json.dumps(query_params, sort_keys=True)
    query_string = final_query + params_str
    cache_key = hashlib.md5(query_string.encode('utf-8')).hexdigest()
    if DEBUG: print(f"Generated cache key: {cache_key}")

    try:
        print("Cache hit for key:", cache_key)
        cached_result = cbCache.get(cache_key).value
        if DEBUG: print(f"Cache hit for key: {cache_key}")
        return jsonify(cached_result)
    except DocumentNotFoundException:
        if DEBUG: print(f"Cache miss for DocId: {cache_key}")
        try:
            result = cluster.query(final_query, **query_params)
            data = [row for row in result]
            cbCache.upsert(cache_key, data)
            return jsonify(data)
        except CouchbaseException as e:
            if DEBUG: print(traceback.format_exc())
            return jsonify([]), 500
        except Exception as e:
            if DEBUG: print(f"Error executing query: {e}")
            return jsonify([]), 500
    except CouchbaseException:
        if DEBUG: print(traceback.format_exc())
        return jsonify([]), 500
    except Exception as e:
        if DEBUG: print(f"Error accessing cache: {e}")
        return jsonify([]), 500

@app.route('/get_pie_data', methods=['POST'])
def get_pie_data():
    filters = request.get_json()
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')

    where_clauses = ["type IS NOT MISSING"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') <= $end_date")
    if search_term:
        escaped_search_term = escape_search_term(search_term)
        where_clauses.append(f"SEARCH(`cbl-log-reader`, '{escaped_search_term}')")

    query = f"""
        SELECT SPLIT(type, ':')[0] AS type_prefix, COUNT(*) AS count
        FROM `cbl-log-reader`
        WHERE {' AND '.join(where_clauses)}
        GROUP BY SPLIT(type, ':')[0]
    """
    if DEBUG: print(f"Executing query for /get_pie_data: {query}")

    query_params = {}
    if start_date and end_date:
        query_params = {'start_date': start_date, 'end_date': end_date}
    if DEBUG: print(f"Query parameters: {query_params}")

    params_str = json.dumps(query_params, sort_keys=True)
    query_string = query + params_str
    cache_key = hashlib.md5(query_string.encode('utf-8')).hexdigest()
    if DEBUG: print(f"Generated cache key: {cache_key}")

    try:
        print("Cache hit for key:", cache_key)
        cached_result = cbCache.get(cache_key).value
        if DEBUG: print(f"Cache hit for key: {cache_key}")
        return jsonify(cached_result)
    except DocumentNotFoundException:
        if DEBUG: print(f"Cache miss for DocId: {cache_key}")
        try:
            result = cluster.query(query, **query_params)
            data = [row for row in result]
            cbCache.upsert(cache_key, data)
            return jsonify(data)
        except CouchbaseException:
            if DEBUG: print(traceback.format_exc())
            return jsonify([]), 500
        except Exception as e:
            if DEBUG: print(f"Error executing query: {e}")
            return jsonify([]), 500
    except CouchbaseException:
        if DEBUG: print(traceback.format_exc())
        return jsonify([]), 500
    except Exception as e:
        if DEBUG: print(f"Error accessing cache: {e}")
        return jsonify([]), 500

@app.route('/get_raw_data', methods=['POST'])
def get_raw_data():
    filters = request.get_json()
    if DEBUG: print(f"Request payload for /get_raw_data: {filters}")

    use_specific_type = filters.get('use_specific_type', False)
    types = filters.get('types', [])
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')
    # Get limit from filters, default to 2000 if not provided
    try:
        limit = int(filters.get('limit', 2000))
    except (ValueError, TypeError):
        limit = 2000  # Fallback to default if not an integer

    type_field = "type" if use_specific_type else "SPLIT(type, ':')[0]"

    where_clauses = ["dt IS NOT MISSING", "type IS NOT NULL", "dt IS NOT NULL"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') <= $end_date")
    if types:
        type_values = [f"'{t}'" for t in types]
        where_clauses.append(f"{type_field} IN [{', '.join(type_values)}]")
   
    if search_term:
        fts_query_str = build_fts_query(search_term, "rawLog")
        if DEBUG:
            print("NEW: ", fts_query_str, " | ", search_term, "\n")
        where_clauses.append(f"SEARCH(`cbl-log-reader`, '{fts_query_str}')")

    # Base query without LIMIT
    query = f"""
        SELECT dt,type, error, rawLog, processId
        FROM `cbl-log-reader`
        WHERE {' AND '.join(where_clauses)}
        ORDER BY dt ASC
    """
    
    # Add LIMIT only if limit is greater than 0
    if limit > 0:
        query += f" LIMIT {limit}"
        
    if DEBUG: print(f"Executing query for /get_raw_data: {query}")

    query_params = {}
    if start_date and end_date:
        query_params = {'start_date': start_date, 'end_date': end_date}
    if DEBUG: print(f"Query parameters: {query_params}")

    params_str = json.dumps(query_params, sort_keys=True)
    query_string = query + params_str
    cache_key = hashlib.md5(query_string.encode('utf-8')).hexdigest()
    if DEBUG: print(f"Generated cache key: {cache_key}")

    try:
        print("Cache hit for key:", cache_key)
        cached_result = cbCache.get(cache_key).value
        if DEBUG: print(f"Cache hit for key: {cache_key}")
        return jsonify(cached_result)
    except DocumentNotFoundException:
        if DEBUG: print(f"Cache miss for DocId: {cache_key}")
        try:
            result = cluster.query(query, **query_params)
            data = [row for row in result]
            cbCache.upsert(cache_key, data)
            return jsonify(data)
        except CouchbaseException:
            if DEBUG: print(traceback.format_exc())
            return jsonify([]), 500
        except Exception as e:
            if DEBUG: print(f"Error executing query: {e}")
            return jsonify([]), 500
    except CouchbaseException:
        if DEBUG: print(traceback.format_exc())
        return jsonify([]), 500
    except Exception as e:
        if DEBUG: print(f"Error accessing cache: {e}")
        return jsonify([]), 500

@app.route('/get_log_report', methods=['GET'])
def get_log_data():
    try:
        data = collection.get("log_report").value
        return jsonify(data)
    except DocumentNotFoundException:
        if DEBUG: print("Warning doc `log_report` not found")
        return jsonify([]), 500
    except CouchbaseException:
        if DEBUG: print(traceback.format_exc())
        return jsonify([]), 500
    except Exception as e:
        if DEBUG: print(f"Error GET `log_report doc: {e}")
        return jsonify([]), 500

if __name__ == '__main__':
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule}")
    app.run(debug=False)