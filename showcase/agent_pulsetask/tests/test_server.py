import unittest
import json
import os
import sys

# Add the backend directory to the system path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from server import app

class APITestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.test_client()  # Create a test client for the Flask application

    def test_health_check(self):
        response = self.app.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'healthy')

    def test_create_task(self):
        response = self.app.post('/api/tasks', json={'title': 'Test Task', 'status': 'todo'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['title'], 'Test Task')

    def test_get_tasks(self):
        response = self.app.get('/api/tasks')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.get_json(), list)

    def test_update_task(self):
        self.app.post('/api/tasks', json={'title': 'Update Task', 'status': 'doing'})
        response = self.app.patch('/api/tasks/1', json={'title': 'Updated Task', 'status': 'done'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['title'], 'Updated Task')

    def test_delete_task(self):
        self.app.post('/api/tasks', json={'title': 'Delete Task', 'status': 'todo'})
        response = self.app.delete('/api/tasks/1')
        self.assertEqual(response.status_code, 204)

    def test_stats(self):
        response = self.app.get('/api/stats')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('total' in response.get_json())

if __name__ == '__main__':
    unittest.main()