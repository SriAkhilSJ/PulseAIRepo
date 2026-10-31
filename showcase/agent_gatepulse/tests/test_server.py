import unittest
import json
import time
import datetime
import threading
import requests

class TestRateLimiter(unittest.TestCase):
    BASE_URL = 'http://localhost:8000/api'

    def setUp(self):
        requests.post(f'{self.BASE_URL}/reset')

    def test_single_consume_within_quota(self):
        response = requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('accepted', response.json()['status'])
        self.assertEqual(response.json()['remaining'], 4)

    def test_rate_limit_exceeded(self):
        for _ in range(5):
            requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        response = requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('rejected', response.json()['status'])

    def test_client_isolation(self):
        for _ in range(5):
            requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        response_B = requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_B'})
        self.assertEqual(response_B.status_code, 200)

    def test_advance_time(self):
        for _ in range(5):
            requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        # Simulating time passing 
        time.sleep(10)
        response = requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        self.assertEqual(response.status_code, 200)

    def test_metrics_accuracy(self):
        for _ in range(3):
            requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        response = requests.get(f'{self.BASE_URL}/metrics')
        metrics = response.json()
        self.assertEqual(metrics['total_requests'], 3)
        self.assertEqual(metrics['accepted_requests'], 3)

    def test_reset(self):
        for _ in range(3):
            requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'client_A'})
        requests.post(f'{self.BASE_URL}/reset')
        response = requests.get(f'{self.BASE_URL}/metrics')
        metrics = response.json()
        self.assertEqual(metrics['total_requests'], 0)

    def test_concurrency(self):
        def make_requests():
            for _ in range(3):
                requests.post(f'{self.BASE_URL}/consume', json={'client_id': 'concurrent_client'})

        threads = [threading.Thread(target=make_requests) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

if __name__ == '__main__':
    unittest.main()