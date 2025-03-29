from flask import Flask, render_template, jsonify, request
from couchbase.cluster import Cluster, ClusterOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import CouchbaseException
import json

app = Flask(__name__)

# Load configuration
try:
    with open('config.json') as f:
        config = json.load(f)
except FileNotFoundError:
    print("Error: config.json file not found. Please create a config.json file with the required configuration.")
    exit(1)
except json.JSONDecodeError:
    print("Error: config.json is not a valid JSON file.")
    exit(1)

# Validate required configuration keys
required_keys = ['cb-cluster-host', 'cb-bucket-user', 'cb-bucket-user-password', 'cb-bucket-name']
missing_keys = [key for key in required_keys if key not in config]
if missing_keys:
    print(f"Error: Missing required configuration keys in config.json: {missing_keys}")
    print("Required keys are: 'cb-cluster-host', 'cb-bucket-user', 'cb-bucket-user-password', 'cb-bucket-name'")
    exit(1)

# Initialize Couchbase cluster
try:
    cluster = Cluster(f"couchbase://{config['cb-cluster-host']}", 
                      ClusterOptions(PasswordAuthenticator(config['cb-bucket-user'], config['cb-bucket-user-password'])))
    bucket = cluster.bucket(config['cb-bucket-name'])
    collection = bucket.default_collection()
except Exception as e:
    print(f"Error connecting to Couchbase cluster: {e}")
    exit(1)

# Function to escape special characters for Couchbase FTS query string syntax
def escape_fts_query_string(search_term):
    fts_special_chars = r'+-&&||!(){}[]^"~*?:\\'
    escaped_term = ''
    for char in search_term:
        if char in fts_special_chars:
            escaped_term += '\\' + char
        else:
            escaped_term += char
    return escaped_term

# Function to escape the search term for N1QL and FTS
def escape_search_term(search_term):
    # Step 1: Escape special characters for FTS query string syntax
    fts_escaped = escape_fts_query_string(search_term)
    # Step 2: Escape single quotes and backslashes for N1QL string literals
    # First, escape backslashes by doubling them (N1QL requires \\ to represent a single \)
    n1ql_escaped = fts_escaped.replace('\\', '\\\\')
    # Then, escape single quotes by doubling them
    n1ql_escaped = n1ql_escaped.replace("'", "''")
    return n1ql_escaped

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
    try:
        result = cluster.query(query)
        for row in result:
            min_dt = row['min_dt']
            max_dt = row['max_dt']
            print(f"Actual date range from database: min_dt={min_dt}, max_dt={max_dt}")
            return jsonify({
                'start_date': min_dt[:10],  # Extract YYYY-MM-DD
                'end_date': max_dt[:10]
            })
    except Exception as e:
        print(f"Error fetching date range: {e}")
        # Fallback to a more reasonable default (e.g., a past date range)
        return jsonify({'start_date': '2023-01-01', 'end_date': '2023-12-31'}), 500

@app.route('/get_types', methods=['GET'])
def get_types():
    query = """
        SELECT DISTINCT type
        FROM `cbl-log-reader`
        WHERE type IS NOT NULL
        ORDER BY type
    """
    try:
        result = cluster.query(query)
        types = [row['type'] for row in result]
        return jsonify(types)
    except Exception as e:
        print(f"Error fetching types: {e}")
        return jsonify([]), 500

@app.route('/get_chart_data', methods=['POST'])
def get_chart_data():
    filters = request.get_json()
    print(f"Request payload for /get_chart_data: {filters}")

    use_specific_type = filters.get('use_specific_type', False)
    grouping_mode = filters.get('grouping_mode', 'by-second')
    error_filter = filters.get('error_filter', False)
    types = filters.get('types', [])
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')

    print(f"Filter parameters - use_specific_type: {use_specific_type}")
    print(f"Filter parameters - grouping_mode: {grouping_mode}")
    print(f"Filter parameters - error_filter: {error_filter}")
    print(f"Filter parameters - types: {types}")
    print(f"Filter parameters - search_term: {search_term}")

    type_field = "type" if use_specific_type else "SPLIT(type, ':')[0]"
    print(f"Type field determined: {type_field}")

    where_clauses = ["dt IS NOT MISSING"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') < $end_date")
    where_clauses.extend(["type IS NOT NULL", "dt IS NOT NULL"])
    
    # Add SEARCH condition if search_term is provided
    if search_term:
        escaped_search_term = escape_search_term(search_term)
        where_clauses.append(f"SEARCH(rawLog, '{escaped_search_term}')")
    
    print(f"Where clauses after date range and search: {where_clauses}")

    type_where_clause = "TRUE"
    if types:
        type_values = [f"'{t}'" for t in types]
        type_where_clause = f"{type_field} IN [{', '.join(type_values)}]"
    print(f"Type where clause: {type_where_clause}")

    group_by_clause = "SUBSTR(dt, 0, 19)"
    if grouping_mode == "by-minute":
        group_by_clause = "SUBSTR(dt, 0, 16)"

    main_query = f"""
            SELECT REPLACE({group_by_clause}, 'T', ' ') AS second, {type_field} AS type, COUNT(*) AS count
            FROM `cbl-log-reader`
            WHERE {' AND '.join(where_clauses)}
            GROUP BY REPLACE({group_by_clause}, 'T', ' '), {type_field}
    """
    print(f"Main query constructed: {main_query}")

    error_query = f"""
                SELECT REPLACE({group_by_clause}, 'T', ' ') AS second, 'Error' AS type, COUNT(*) AS count
                FROM `cbl-log-reader`
                WHERE {' AND '.join(where_clauses)} AND error = True
                GROUP BY REPLACE({group_by_clause}, 'T', ' ')
    """
    print(f"Error query constructed: {error_query}")

    final_query = f"""
            SELECT combined.second, combined.type, combined.count
            FROM (
                {main_query}
                {'UNION ALL' if error_filter else ''}
                {error_query if error_filter else ''}
            ) AS combined
            ORDER BY combined.second
    """
    print(f"Final query: {final_query}")

    query_params = {}
    if start_date and end_date:
        query_params = {'start_date': start_date, 'end_date': end_date}
    print(f"Query parameters: {query_params}")

    try:
        result = cluster.query(final_query, **query_params)
        data = [row for row in result]
        return jsonify(data)
    except Exception as e:
        print(f"Error executing query: {e}")
        return jsonify([]), 500

@app.route('/get_pie_data', methods=['POST'])
def get_pie_data():
    filters = request.get_json()
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')

    where_clauses = ["type IS NOT MISSING"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') < $end_date")
    
    # Add SEARCH condition if search_term is provided
    if search_term:
        escaped_search_term = escape_search_term(search_term)
        where_clauses.append(f"SEARCH(rawLog, '{escaped_search_term}')")

    query = f"""
        SELECT SPLIT(type, ':')[0] AS type_prefix, COUNT(*) AS count
        FROM `cbl-log-reader`
        WHERE {' AND '.join(where_clauses)}
        GROUP BY SPLIT(type, ':')[0]
    """
    print(f"Executing query for /get_pie_data: {query}")

    query_params = {}
    if start_date and end_date:
        query_params = {'start_date': start_date, 'end_date': end_date}
    print(f"Query parameters: {query_params}")

    try:
        result = cluster.query(query, **query_params)
        data = [row for row in result]
        return jsonify(data)
    except Exception as e:
        print(f"Error executing query: {e}")
        return jsonify([]), 500


@app.route('/get_raw_data', methods=['POST'])
def get_raw_data():
    filters = request.get_json()
    print(f"Request payload for /get_raw_data: {filters}")

    use_specific_type = filters.get('use_specific_type', False)
    types = filters.get('types', [])
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    search_term = filters.get('search_term', '')

    # Determine type field based on specific type mode
    type_field = "type" if use_specific_type else "SPLIT(type, ':')[0]"

    # Build WHERE clauses
    where_clauses = ["dt IS NOT MISSING", "type IS NOT NULL", "dt IS NOT NULL"]
    if start_date and end_date:
        where_clauses.append("REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') >= $start_date AND REPLACE(SUBSTR(dt, 0, 19), 'T', ' ') < $end_date")
    
    if types:
        type_values = [f"'{t}'" for t in types]
        where_clauses.append(f"{type_field} IN [{', '.join(type_values)}]")
    
    if search_term:
        escaped_search_term = escape_search_term(search_term)
        where_clauses.append(f"SEARCH(rawLog, '{escaped_search_term}')")

    # Construct the query
    query = f"""
        SELECT dt, type, error, rawLog
        FROM `cbl-log-reader`
        WHERE {' AND '.join(where_clauses)}
        ORDER BY dt
        LIMIT 1000
    """
    print(f"Executing query for /get_raw_data: {query}")

    # Set query parameters
    query_params = {}
    if start_date and end_date:
        query_params = {'start_date': start_date, 'end_date': end_date}
    print(f"Query parameters: {query_params}")

    try:
        result = cluster.query(query, **query_params)
        data = [row for row in result]
        return jsonify(data)
    except Exception as e:
        print(f"Error executing query: {e}")
        return jsonify([]), 500


if __name__ == '__main__':
    app.run(debug=False)