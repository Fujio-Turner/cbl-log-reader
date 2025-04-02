from flask import Flask, render_template, jsonify, request
import traceback
from couchbase.cluster import Cluster, ClusterOptions , QueryOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import CouchbaseException, DocumentNotFoundException
import json
import sys
import hashlib
import re
from datetime import datetime, timedelta

print("Starting app.py from /Users/fujio.turner/Documents/demo/cbl-log-reader/cbl-log-reader/")

DEBUG = True
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



def build_fts_query_2(filters):
    use_specific_type = filters.get('use_specific_type', False)
    all_type_selected = filters.get('allTypeSelected', False)
    types = filters.get('types', [])
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')
    try:
        limit = int(filters.get('limit', 500))
    except (ValueError, TypeError):
        limit = 500

    fts_query = {
        "explain": True,
        "fields": ["*"],
        "highlight": {},
        "query": {
            "conjuncts": [],
            "disjuncts": []
        },
        "index": "cbl_rawLog_v3",
        "sort": [{"by": "field", "field": "dtEpoch", "mode": "min", "missing": "last"}]
    }

    if limit > 0:
        fts_query["size"] = limit

    # Add date range to conjuncts (required condition)
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date.replace(" ", "T") if "T" not in start_date else start_date, 
                                       "%Y-%m-%dT%H:%M:%S.%f" if '.' in start_date else "%Y-%m-%dT%H:%M:%S")
            end_dt = datetime.strptime(end_date.replace(" ", "T") if "T" not in end_date else end_date, 
                                     "%Y-%m-%dT%H:%M:%S.%f" if '.' in end_date else "%Y-%m-%dT%H:%M:%S")
            fts_query["query"]["conjuncts"].append({
                "field": "dtEpoch",
                "min": start_dt.timestamp(),
                "max": end_dt.timestamp(),
                "inclusive_min": True,
                "inclusive_max": True
            })
        except ValueError as e:
            if DEBUG: print(f"Error parsing date range: {e}")

    # Handle search term
    if search_term:
        search_term = search_term.lstrip('+')
        if any(op in search_term.upper() for op in [' AND ', ' OR ', ' NOT ']):
            terms = re.split(r'(\s+(?:AND|OR|NOT)\s+)', search_term, flags=re.IGNORECASE)
            terms = [t.strip() for t in terms if t.strip()]
            for term in terms:
                if term.upper() in ['AND', 'OR', 'NOT']:
                    if term.upper() == 'OR' and DEBUG:
                        print("Warning: OR in disjuncts; terms will boost relevance")
                    if term.upper() == 'NOT' and DEBUG:
                        print("Warning: NOT not fully supported; ignoring")
                    continue
                field_value = term[1:] if term.startswith('+') else term
                if ':' in field_value:
                    field, value = field_value.split(':', 1)
                    field = field.strip().lower()
                    value = value.strip()
                    if field == "processid":
                        try:
                            int_value = int(value)
                            fts_query["query"]["conjuncts"].append({
                                "field": "processId",
                                "min": int_value,
                                "max": int_value,
                                "inclusive_min": True,
                                "inclusive_max": True
                            })
                        except ValueError:
                            if '*' in value:
                                fts_query["query"]["disjuncts"].append({
                                    "wildcard": escape_fts_query_string(value),
                                    "field": "processId"
                                })
                            else:
                                fts_query["query"]["disjuncts"].append({
                                    "match": escape_fts_query_string(value),
                                    "field": "processId"
                                })
                    else:
                        if '*' in value:
                            fts_query["query"]["disjuncts"].append({
                                "wildcard": escape_fts_query_string(value),
                                "field": field
                            })
                        else:
                            fts_query["query"]["disjuncts"].append({
                                "match": escape_fts_query_string(value),
                                "field": field
                            })
                else:
                    if '*' in field_value:
                        fts_query["query"]["disjuncts"].append({
                            "wildcard": escape_fts_query_string(field_value),
                            "field": "rawLog"
                        })
                    else:
                        fts_query["query"]["disjuncts"].append({
                            "match": escape_fts_query_string(field_value),
                            "field": "rawLog"
                        })
        elif ':' in search_term:
            field_value = search_term[1:] if search_term.startswith('+') else search_term
            field, value = field_value.split(':', 1)
            field = field.strip().lower()
            value = value.strip()
            if field == "processid":
                try:
                    int_value = int(value)
                    fts_query["query"]["conjuncts"].append({
                        "field": "processId",
                        "min": int_value,
                        "max": int_value,
                        "inclusive_min": True,
                        "inclusive_max": True
                    })
                except ValueError:
                    if '*' in value:
                        fts_query["query"]["disjuncts"].append({
                            "wildcard": escape_fts_query_string(value),
                            "field": "processId"
                        })
                    else:
                        fts_query["query"]["disjuncts"].append({
                            "match": escape_fts_query_string(value),
                            "field": "processId"
                        })
            else:
                if '*' in value:
                    fts_query["query"]["disjuncts"].append({
                        "wildcard": escape_fts_query_string(value),
                        "field": field
                    })
                else:
                    fts_query["query"]["disjuncts"].append({
                        "match": escape_fts_query_string(value),
                        "field": field
                    })
        else:
            if '*' in search_term:
                fts_query["query"]["disjuncts"].append({
                    "wildcard": escape_fts_query_string(search_term),
                    "field": "rawLog"
                })
            else:
                fts_query["query"]["disjuncts"].append({
                    "match": escape_fts_query_string(search_term),
                    "field": "rawLog"
                })

    # Handle type filters
    if not all_type_selected and types:
        # Create a disjuncts array for types (OR condition among types)
        type_disjuncts = []
        for t in types:
            if '*' in t:
                type_disjuncts.append({
                    "wildcard": escape_fts_query_string(t),
                    "field": "type"
                })
            else:
                type_disjuncts.append({
                    "match": escape_fts_query_string(t),
                    "field": "type"
                })
        # Add the type disjuncts as a required condition in conjuncts
        if type_disjuncts:
            fts_query["query"]["conjuncts"].append({
                "disjuncts": type_disjuncts
            })

    # Clean up empty arrays
    if not fts_query["query"]["conjuncts"]:
        del fts_query["query"]["conjuncts"]
    if not fts_query["query"]["disjuncts"]:
        del fts_query["query"]["disjuncts"]
    if not fts_query["query"].get("conjuncts") and not fts_query["query"].get("disjuncts"):
        fts_query["query"] = {"match_all": {}}

    return json.dumps(fts_query, ensure_ascii=False)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_date_range', methods=['GET'])
def get_date_range():
    query = """
        SELECT MIN(dt) AS min_dt, MAX(dt) AS max_dt
        FROM `cbl-log-reader`
        WHERE dt IS NOT MISSING 
        AND dt IS NOT MISSING
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

    where_clauses = ["dt IS NOT MISSING", "type IS NOT MISSING"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') <= $end_date")

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
    if DEBUG: print(f"Request payload for /get_pie_data: {filters}")

    use_specific_type = filters.get('use_specific_type', False)
    # Determine grouping field based on use_specific_type
    group_field = "type" if use_specific_type else "mainType"
    group_type = "specific" if use_specific_type else "general"

    # Get FTS query string
    fts_query_str = build_fts_query_2(filters)
    
    # Parse the FTS query string to modify it
    fts_query = json.loads(fts_query_str)
    
    # Remove limit and sort since we're counting
    if "size" in fts_query:
        del fts_query["size"]
    if "sort" in fts_query:
        del fts_query["sort"]
    
    # Update fields to include only the relevant field
    fts_query["fields"] = [group_field]
    
    # Convert back to string
    fts_query_str = json.dumps(fts_query, ensure_ascii=False)

    # Construct the N1QL query with FTS and grouping
    query = f"""
        SELECT
            meta.fields.{group_field} AS type_prefix,
            COUNT(meta.fields.{group_field}) AS count
        FROM `{config['cb-bucket-name']}` USE INDEX (cbl_rawLog_v3)
            LET meta = SEARCH_META()
        WHERE 
            SEARCH(`{config['cb-bucket-name']}`, {fts_query_str})
        GROUP BY 
            meta.fields.{group_field}
    """
    if DEBUG: print(f"Executing query for /get_pie_data: {query}")

    # Generate cache key
    query_string = query + json.dumps(filters, sort_keys=True)
    cache_key = hashlib.md5(query_string.encode('utf-8')).hexdigest()
    if DEBUG: print(f"Generated cache key: {cache_key}")

    # Try cache first
    try:
        cached_result = cbCache.get(cache_key).value
        if DEBUG: print(f"Cache hit for key: {cache_key}")
        return jsonify({"status": "success", "data": cached_result, "type": group_type}), 200
    except DocumentNotFoundException:
        if DEBUG: print(f"Cache miss for DocId: {cache_key}")
        try:
            result = cluster.query(query)
            rows = [row for row in result]
            cbCache.upsert(cache_key, rows)
            if DEBUG: print(f"Query executed successfully, returned {len(rows)} rows")
            return jsonify({"status": "success", "data": rows, "type": group_type}), 200
        except CouchbaseException as e:
            if DEBUG: print(f"Couchbase error executing query: {traceback.format_exc()}")
            return jsonify({"status": "error", "message": str(e), "type": group_type}), 500
        except Exception as e:
            if DEBUG: print(f"Error executing query: {e}")
            return jsonify({"status": "error", "message": str(e), "type": group_type}), 500
    except CouchbaseException as e:
        if DEBUG: print(f"Couchbase error accessing cache: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e), "type": group_type}), 500
    except Exception as e:
        if DEBUG: print(f"Error accessing cache: {e}")
        return jsonify({"status": "error", "message": str(e), "type": group_type}), 500

@app.route('/get_raw_data', methods=['POST'])
def get_raw_data():
    filters = request.get_json()
    if DEBUG: print(f"Request payload for /get_raw_data: {filters}")

    use_specific_type = filters.get('use_specific_type', False)
    type_field = "type" if use_specific_type else "SPLIT(type, ':')[0]"

    fts_query_str = build_fts_query_2(filters)

    query = f"""
        SELECT dt, type, error, rawLog, processId
        FROM `{config['cb-bucket-name']}` USE INDEX (cbl_rawLog_v3)
        WHERE SEARCH(`{config['cb-bucket-name']}`, {fts_query_str})
    """

    if DEBUG: print(f"Executing query for /get_raw_data: {query}")

    query_string = query + json.dumps(filters, sort_keys=True)
    cache_key = hashlib.md5(query_string.encode('utf-8')).hexdigest()
    if DEBUG: print(f"Generated cache key: {cache_key}")

    try:
        cached_result = cbCache.get(cache_key).value
        if DEBUG: print(f"Cache hit for key: {cache_key}")
        return jsonify({"status": "success", "data": cached_result}), 200
    except DocumentNotFoundException:
        if DEBUG: print(f"Cache miss for DocId: {cache_key}")
        try:
            result = cluster.query(query)
            rows = [row for row in result]
            cbCache.upsert(cache_key, rows)
            if DEBUG: print(f"Query executed successfully, returned {len(rows)} rows")
            return jsonify({"status": "success", "data": rows}), 200
        except CouchbaseException as e:
            if DEBUG: print(f"Couchbase error executing query: {traceback.format_exc()}")
            return jsonify({"status": "error", "message": str(e)}), 500
        except Exception as e:
            if DEBUG: print(f"Error executing query: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    except CouchbaseException as e:
        if DEBUG: print(f"Couchbase error accessing cache: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        if DEBUG: print(f"Error accessing cache: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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