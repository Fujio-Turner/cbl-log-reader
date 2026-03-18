from flask import Flask, render_template, jsonify, request
import traceback
from couchbase.cluster import Cluster, ClusterOptions, QueryOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import CouchbaseException, DocumentNotFoundException
import json
import sys
import os
import hashlib
import re
from datetime import datetime, timedelta

# Global FTS index name
FTS_INDEX_NAME = "cbl_rawLog_v3"
web_port = 5099

print("Starting app.py ")

app = Flask(__name__)

# Load configuration
if len(sys.argv) < 2:
    print("Error: Please provide config.json as an argument (e.g., python3 app.py config.json)")
    exit(1)

config_file = sys.argv[1]
try:
    with open(config_file) as f:
        config = json.load(f)
        DEBUG = config.get('debug', False)
except FileNotFoundError:
    print(f"Error: Config file '{config_file}' not found.")
    exit(1)
except json.JSONDecodeError:
    print(f"Error: '{config_file}' is not a valid JSON file.")
    exit(1)

required_keys = ['cb-cluster-host', 'cb-bucket-user', 'cb-bucket-user-password', 'cb-bucket-name']
missing_keys = [key for key in required_keys if key not in config]
if missing_keys:
    if DEBUG: print(f"Error: Missing required configuration keys in {config_file}: {missing_keys}")
    exit(1)

cb_host = os.environ.get('CBL_CB_HOST', config['cb-cluster-host'])
try:
    cluster = Cluster(f"couchbase://{cb_host}", 
                      ClusterOptions(PasswordAuthenticator(config['cb-bucket-user'], config['cb-bucket-user-password'])))
    bucket = cluster.bucket(config['cb-bucket-name'])
    collection = bucket.default_collection()
    cbCacheBucket = cluster.bucket("cache")
    cbCache = cbCacheBucket.default_collection()
except Exception as e:
    if DEBUG: print(f"Error connecting to Couchbase cluster: {e}")
    exit(1)

FIELD_ALIASES = {
    "rawlog": "rawLog",
    "type": "type",
    "maintype": "mainType",
    "processid": "processId",
    "pid": "processId",
    "error": "error",
    "dt": "dt",
    "dtepoch": "dtEpoch",
}

def resolve_field(field_name):
    """Resolve user-typed field name to actual index field name via alias map."""
    resolved = FIELD_ALIASES.get(field_name.lower())
    if resolved is None:
        raise ValueError(f"Unknown field: '{field_name}'. Valid fields: {', '.join(sorted(set(FIELD_ALIASES.values())))}")
    return resolved

def build_leaf(field, value, is_phrase=False):
    """Build a single FTS leaf clause based on field type and value."""
    if field == "processId":
        try:
            int_value = int(value)
            return {
                "field": "processId",
                "min": int_value,
                "max": int_value,
                "inclusive_min": True,
                "inclusive_max": True
            }
        except ValueError:
            raise ValueError(f"processId must be numeric, got: '{value}'")
    elif field == "error":
        lower_val = value.lower()
        if lower_val in ("true", "yes", "1"):
            return {"field": "error", "bool": True}
        elif lower_val in ("false", "no", "0"):
            return {"field": "error", "bool": False}
        else:
            raise ValueError(f"error field must be true/false/yes/no/1/0, got: '{value}'")
    elif is_phrase:
        return {"match_phrase": value, "field": field}
    elif value.endswith("*") and value.count("*") == 1:
        return {"prefix": value[:-1], "field": field}
    elif "*" in value:
        return {"wildcard": value, "field": field}
    else:
        return {"match": value, "field": field}

def tokenize_search(search_term):
    """
    Tokenize search input into structured tokens.
    Handles quoted phrases, field:value, operators (AND/OR/NOT), and negation (-term).
    Returns list of dicts: {"type": "term"|"phrase"|"operator"|"field", "value": str, "field": str|None, "negated": bool}
    """
    tokens = []
    i = 0
    s = search_term.strip()
    while i < len(s):
        # Skip whitespace
        if s[i] == ' ':
            i += 1
            continue
        # Quoted phrase
        if s[i] == '"':
            end = s.find('"', i + 1)
            if end == -1:
                end = len(s)
            phrase = s[i+1:end]
            tokens.append({"type": "phrase", "value": phrase, "field": None, "negated": False})
            i = end + 1
            continue
        # Collect a word (until space or quote)
        j = i
        while j < len(s) and s[j] != ' ' and s[j] != '"':
            j += 1
        word = s[i:j]
        i = j
        # Check for operators
        if word.upper() in ("AND", "OR", "NOT"):
            tokens.append({"type": "operator", "value": word.upper(), "field": None, "negated": False})
            continue
        # Check for negation
        negated = False
        if word.startswith("-") and len(word) > 1:
            negated = True
            word = word[1:]
        # Check for field:value
        if ":" in word:
            field_part, value_part = word.split(":", 1)
            tokens.append({"type": "field", "value": value_part, "field": field_part, "negated": negated})
        else:
            tokens.append({"type": "term", "value": word, "field": None, "negated": negated})
    return tokens

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
        "fields": ["*"],
        "highlight": {},
        "query": {
            "conjuncts": []
        },
        "index": FTS_INDEX_NAME,
        "sort": [{"by": "field", "field": "dtEpoch", "mode": "min", "missing": "last"}]
    }

    if DEBUG:
        fts_query["explain"] = True

    if limit > 0:
        fts_query["size"] = limit

    # Add date range to conjuncts (required condition)
    # Prefer raw epoch values from chart zoom (avoids timezone conversion issues)
    start_epoch = filters.get('start_epoch')
    end_epoch = filters.get('end_epoch')
    if start_epoch and end_epoch:
        fts_query["query"]["conjuncts"].append({
            "field": "dtEpoch",
            "min": float(start_epoch),
            "max": float(end_epoch),
            "inclusive_min": True,
            "inclusive_max": True
        })
    elif start_date and end_date:
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
        # Special case for bare "error" / "errors"
        if search_term.strip().lower() in ('error', 'errors'):
            fts_query["query"]["conjuncts"].append({
                "field": "error",
                "bool": True
            })
        else:
            tokens = tokenize_search(search_term)
            # Split tokens by OR into groups; each group is ANDed together
            or_groups = []
            current_group = []
            must_not_clauses = []
            # Track the operator context
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok["type"] == "operator":
                    if tok["value"] == "OR":
                        or_groups.append(current_group)
                        current_group = []
                    elif tok["value"] == "NOT":
                        # Next token is negated
                        if i + 1 < len(tokens):
                            next_tok = tokens[i + 1]
                            next_tok["negated"] = True
                            # Let the next iteration handle it
                    # AND is default, just continue
                    i += 1
                    continue

                # Build the leaf clause
                if tok["field"] is not None:
                    field = resolve_field(tok["field"])
                    clause = build_leaf(field, tok["value"])
                else:
                    is_phrase = (tok["type"] == "phrase")
                    clause = build_leaf("rawLog", tok["value"], is_phrase=is_phrase)

                if tok["negated"]:
                    must_not_clauses.append(clause)
                else:
                    current_group.append(clause)
                i += 1

            # Don't forget the last group
            if current_group:
                or_groups.append(current_group)

            # Build the boolean tree
            if or_groups:
                if len(or_groups) == 1 and len(or_groups[0]) == 1 and not must_not_clauses:
                    # Single term, add directly
                    fts_query["query"]["conjuncts"].append(or_groups[0][0])
                elif len(or_groups) == 1:
                    # Single AND group
                    for clause in or_groups[0]:
                        fts_query["query"]["conjuncts"].append(clause)
                else:
                    # Multiple OR groups: each group is a conjuncts, wrapped in disjuncts
                    or_clauses = []
                    for group in or_groups:
                        if len(group) == 1:
                            or_clauses.append(group[0])
                        else:
                            or_clauses.append({"conjuncts": group})
                    fts_query["query"]["conjuncts"].append({"disjuncts": or_clauses})

            if must_not_clauses:
                fts_query["query"]["conjuncts"].append({
                    "must_not": {"disjuncts": must_not_clauses}
                })

    # Handle type filters
    if not all_type_selected and types:
        type_disjuncts = []
        for t in types:
            if '*' in t:
                type_disjuncts.append({
                    "wildcard": t,
                    "field": "type"
                })
            else:
                type_disjuncts.append({
                    "match": t,
                    "field": "type"
                })
        if type_disjuncts:
            fts_query["query"]["conjuncts"].append({
                "disjuncts": type_disjuncts
            })

    # Clean up empty arrays
    if not fts_query["query"]["conjuncts"]:
        del fts_query["query"]["conjuncts"]
    if not fts_query["query"].get("conjuncts"):
        fts_query["query"] = {"match_all": {}}

    return json.dumps(fts_query, ensure_ascii=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search-help')
def search_help():
    return render_template('search-help.html')

@app.route('/debug_query', methods=['POST'])
def debug_query():
    filters = request.get_json()
    fts_query_str = build_fts_query_2(filters)
    return jsonify({"fts_query": json.loads(fts_query_str), "filters": filters})

@app.route('/get_date_range', methods=['GET'])
def get_date_range():
    query = """
        SELECT 
            MIN(dt) AS min_dt,
            MAX(dt) AS max_dt
        FROM `cbl-log-reader`
        WHERE 
            dt IS NOT MISSING
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
        SELECT 
            DISTINCT type
        FROM `cbl-log-reader`
        WHERE 
            type IS NOT NULL
        ORDER BY 
            type
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

    # Determine type field based on use_specific_type
    type_field = "type" if use_specific_type else "mainType"
    group_type = "specific" if use_specific_type else "general"
    if DEBUG: print(f"Type field determined: {type_field}")

    # Get base FTS query string
    fts_query_str = build_fts_query_2(filters)
    
    # Main FTS query
    main_fts_query = json.loads(fts_query_str)
    if "size" in main_fts_query:
        del main_fts_query["size"]
    if "sort" in main_fts_query:
        del main_fts_query["sort"]
    main_fts_query["fields"] = ["dt", type_field]  # Only dt and type_field needed
    main_fts_query_str = json.dumps(main_fts_query, ensure_ascii=False)

    # Error FTS query
    error_fts_query = json.loads(fts_query_str)
    if "size" in error_fts_query:
        del error_fts_query["size"]
    if "sort" in error_fts_query:
        del error_fts_query["sort"]
    error_fts_query["fields"] = ["dt"]  # Only dt needed
    if "conjuncts" not in error_fts_query["query"]:
        error_fts_query["query"]["conjuncts"] = []
    error_fts_query["query"]["conjuncts"].append({
        "field": "error",
        "bool": True
    })
    error_fts_query_str = json.dumps(error_fts_query, ensure_ascii=False)

    # Determine grouping granularity
    group_by_length = 19 if grouping_mode == "by-second" else 16
    group_by_clause = f"SUBSTR(meta.fields.dt, 0, {group_by_length})"

    # Main query
    main_query = f"""
        SELECT 
            REPLACE({group_by_clause}, 'T', ' ') AS second, 
            meta.fields.{type_field} AS type, 
            COUNT(*) AS count
        FROM `{config['cb-bucket-name']}` USE INDEX ({FTS_INDEX_NAME})
            LET meta = SEARCH_META()
        WHERE 
            SEARCH(`{config['cb-bucket-name']}`, {main_fts_query_str})
        GROUP BY 
            REPLACE({group_by_clause}, 'T', ' '), meta.fields.{type_field}
    """

    if DEBUG: print(f"Main query constructed: {main_query}")

    # Error query
    error_query = f"""
        SELECT
            REPLACE({group_by_clause}, 'T', ' ') AS second, 
            'Error' AS type, 
            COUNT(*) AS count
        FROM `{config['cb-bucket-name']}` USE INDEX ({FTS_INDEX_NAME})
            LET meta = SEARCH_META()
        WHERE
            SEARCH(`{config['cb-bucket-name']}`, {error_fts_query_str})
        GROUP BY
            REPLACE({group_by_clause}, 'T', ' ')
    """
    if DEBUG: print(f"Error query constructed: {error_query}")

    # Combine queries
    final_query = f"""
        SELECT 
            combined.second, 
            combined.type, 
            combined.count
        FROM (
            {main_query}
            {'UNION ALL' if error_filter else ''}
            {error_query if error_filter else ''}
        ) AS combined
        ORDER BY 
            combined.second
    """
    if DEBUG: print(f"Final query: {final_query}")

    # Generate cache key
    query_string = final_query + json.dumps(filters, sort_keys=True)
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
            result = cluster.query(final_query)
            data = [row for row in result]
            cbCache.upsert(cache_key, data)
            if DEBUG: print(f"Query executed successfully, returned {len(data)} rows")
            return jsonify({"status": "success", "data": data, "type": group_type}), 200
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
        FROM `{config['cb-bucket-name']}` USE INDEX ({FTS_INDEX_NAME})
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
        SELECT 
            dt, 
            type, 
            error, 
            rawLog, 
            processId
        FROM `{config['cb-bucket-name']}` USE INDEX ({FTS_INDEX_NAME})
        WHERE 
            SEARCH(`{config['cb-bucket-name']}`, {fts_query_str})
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
    app.run(debug=DEBUG, host='0.0.0.0', port=web_port)