import http.server
import socketserver
import sqlite3
import json
import threading
import time
import os

# Database setup
DB_PATH = os.getenv('GATEPULSE_DB', 'rate_limits.db')
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Create table if it doesn't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS requests (
    timestamp REAL,
    client_id TEXT,
    PRIMARY KEY (timestamp, client_id)
)''')

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    # Handle the incoming requests
    
    def do_POST(self):
        if self.path == '/api/consume':
            length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(length))
            client_id = data.get('client_id')
            if not client_id:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'missing client_id'}).encode())
                return
            self.handle_consume(client_id)
        elif self.path == '/api/reset':
            self.handle_reset()

    def handle_consume(self, client_id):
        # Sliding window logic implementation
        now = time.time()
        window_start = now - 10.0
        cursor.execute('DELETE FROM requests WHERE timestamp < ?', (window_start,))
        cursor.execute('SELECT COUNT(*) FROM requests WHERE client_id = ? AND timestamp >= ?', (client_id, window_start))
        count = cursor.fetchone()[0]
        if count >= 5:
            # Rate limit exceeded
            self.send_response(429)
            self.send_header("Retry-After", str(int(10 - (now - (cursor.execute('SELECT MIN(timestamp) FROM requests WHERE client_id = ?', (client_id,)).fetchone()[0] or now)))))
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'rejected', 'client_id': client_id, 'error': 'rate limit exceeded', 'retry_after': int(10 - (now - (cursor.execute('SELECT MIN(timestamp) FROM requests WHERE client_id = ?', (client_id,)).fetchone()[0] or now)))}).encode())
            return
        # Log the request
        cursor.execute('INSERT INTO requests (timestamp, client_id) VALUES (?, ?)', (now, client_id))
        conn.commit()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'accepted', 'client_id': client_id, 'remaining': 4 - count, 'limit': 5, 'window_seconds': 10.0}).encode())

    def handle_reset(self):
        # Resetting the database
        cursor.execute('DELETE FROM requests')
        conn.commit()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'reset', 'message': 'All quotas and history cleared'}).encode())

    def do_GET(self):
        if self.path == '/api/metrics':
            self.handle_metrics()
        elif self.path == '/api/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        else:
            super().do_GET()

    def handle_metrics(self):
        cursor.execute('SELECT COUNT(*) FROM requests')
        total_requests = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM requests WHERE client_id = ? AND timestamp >= ?', ('client_A', time.time() - 10))
        accepted_requests = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM requests WHERE client_id = ? AND timestamp < ?', ('client_A', time.time() - 10))
        rejected_requests = cursor.fetchone()[0]
        rejection_rate = (rejected_requests / total_requests) * 100 if total_requests > 0 else 0
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({
            'total_requests': total_requests,
            'accepted_requests': accepted_requests,
            'rejected_requests': rejected_requests,
            'rejection_rate': rejection_rate,
            'clients': {'client_A': {'accepted': accepted_requests, 'rejected': rejected_requests}}
        }).encode())

# Server setup
PORT = 8000
handler = RequestHandler
with socketserver.TCPServer(('', PORT), handler) as httpd:
    print(f'Serving at port {PORT}')
    httpd.serve_forever()
