import sqlite3
from flask import Flask, jsonify, request

app = Flask(__name__)
DATABASE = 'tasks.db'

# Function to connect to the SQLite database

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize the database and create the tasks table if it doesn't exist

def init_db():
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        status TEXT NOT NULL
    )''')
    conn.commit()
    conn.close()

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'})

@app.route('/api/tasks', methods=['GET', 'POST'])
def manage_tasks():
    conn = get_db_connection()
    if request.method == 'POST':
        new_task = request.json
        cursor = conn.cursor()
        cursor.execute('INSERT INTO tasks (title, status) VALUES (?, ?)', (new_task['title'], new_task['status']))
        conn.commit()
        return jsonify(new_task), 201
    else:
        tasks = conn.execute('SELECT * FROM tasks').fetchall()
        return jsonify([dict(task) for task in tasks]), 200

@app.route('/api/tasks/<int:task_id>', methods=['PATCH', 'DELETE'])
def update_delete_task(task_id):
    conn = get_db_connection()
    if request.method == 'PATCH':
        update_data = request.json
        conn.execute('UPDATE tasks SET title = ?, status = ? WHERE id = ?', (update_data['title'], update_data['status'], task_id))
        conn.commit()
        return jsonify(update_data), 200
    else:
        conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()
        return '', 204

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db_connection()
    total_tasks = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    todo_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', ('todo',)).fetchone()[0]
    doing_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', ('doing',)).fetchone()[0]
    done_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', ('done',)).fetchone()[0]
    conn.close()
    return jsonify({
        'total': total_tasks,
        'todo': todo_tasks,
        'doing': doing_tasks,
        'done': done_tasks
    })

# Initialize the database when the app starts up
if __name__ == '__main__':
    init_db()
    app.run(debug=True)