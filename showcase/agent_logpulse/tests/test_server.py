import pytest
import json
from backend.server import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_ingest_logs(client):
    response = client.post('/api/logs', json={
        'level': 'INFO',
        'message': 'Test log message',
        'source': 'TestSource',
        'timestamp': '2026-10-29T00:00:00'
    })
    assert response.status_code == 201
    assert response.json['message'] == 'Log entry added'


def test_get_logs(client):
    response = client.get('/api/logs?level=INFO')
    logs = json.loads(response.data)
    assert len(logs) > 0


def test_get_stats(client):
    response = client.get('/api/stats')
    stats = json.loads(response.data)
    assert stats['total'] >= 0
    assert stats['error_rate'] is not None
