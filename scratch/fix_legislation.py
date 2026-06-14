with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "return jsonify(sync_status.copy())"
end_marker = "for law in db:"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print("Markers not found!")
    exit(1)

# We want to replace the gap between the return statement of get_sync_status and the start of loop in get_legislation
insert_code = """
        return jsonify(sync_status.copy())

# --- Encyclopedia APIs ---

@app.route('/api/legislation', methods=['GET'])
def get_legislation():
    search = request.args.get('search', '').strip()
    db = load_legislation()
    if not search:
        return jsonify([{
            "id": law["id"],
            "name": law["name"],
            "description": law["description"],
            "articles_count": len(law["articles"]),
            "articles": law["articles"]
        } for law in db])
    
    search_results = []
    """

new_content = content[:start_idx] + insert_code + content[end_idx:]

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("[SUCCESS] app.py legislation route has been fixed!")
