from flask import Flask, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
import time

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///logs.db'
db = SQLAlchemy(app)

class LogEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), index=True)
    message = db.Column(db.String(500))
    source = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, index=True)

    def __repr__(self):
        return f'<LogEntry {self.level} - {self.message}>'

@app.route('/api/logs', methods=['POST'])
def ingest_logs():
    data = request.json
    log_entry = LogEntry(level=data['level'], message=data['message'], source=data['source'], timestamp=data['timestamp'])
    db.session.add(log_entry)
db.session.commit()
    return jsonify({'message': 'Log entry added'}), 201

@app.route('/api/logs', methods=['GET'])
def get_logs():
    level = request.args.get('level')
    search = request.args.get('search')
    limit = request.args.get('limit', default=100, type=int)
    query = LogEntry.query
    if level:
        query = query.filter_by(level=level)
    if search:
        query = query.filter(LogEntry.message.contains(search))
    logs = query.limit(limit).all()
    return jsonify([{'level': log.level, 'message': log.message, 'source': log.source, 'timestamp': log.timestamp} for log in logs])

@app.route('/api/stats', methods=['GET'])
def get_stats():
    total_logs = LogEntry.query.count()
    error_count = LogEntry.query.filter_by(level='ERROR').count()
    error_rate = (error_count / total_logs * 100) if total_logs > 0 else 0
    breakdown = db.session.query(LogEntry.level, db.func.count(LogEntry.id)).group_by(LogEntry.level).all()
    return jsonify({'total': total_logs, 'error_rate': error_rate, 'breakdown': {level: count for level, count in breakdown}})

@app.route('/api/stream')
def stream_logs():
    def generate():
        while True:
            time.sleep(1)  # Adjust the frequency of log streaming
            for log in LogEntry.query.order_by(LogEntry.timestamp.desc()).limit(10).all():
                yield f'data: {log.message} - {log.timestamp}

'  # Simple stream format
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    db.create_all(); db.session.commit()
    app.run(debug=True)
