document.addEventListener('DOMContentLoaded', () => {
    const clientIdSelector = document.getElementById('client_id');
    const sendRequestBtn = document.getElementById('send_request');
    const burstTrafficBtn = document.getElementById('burst_traffic');
    const resetBtn = document.getElementById('reset_simulation');
    const remainingDisplay = document.getElementById('remaining');
    const totalRequestsDisplay = document.getElementById('total_requests');
    const acceptedRequestsDisplay = document.getElementById('accepted_requests');
    const rejectedRequestsDisplay = document.getElementById('rejected_requests');
    const rejectionRateDisplay = document.getElementById('rejection_rate');
    const requestLog = document.getElementById('request_log');
    const feedbackDiv = document.getElementById('feedback');

    function updateMetrics(metrics) {
        totalRequestsDisplay.innerText = metrics.total_requests;
        acceptedRequestsDisplay.innerText = metrics.accepted_requests;
        rejectedRequestsDisplay.innerText = metrics.rejected_requests;
        rejectionRateDisplay.innerText = metrics.rejection_rate.toFixed(2);
    }

    async function logRequest(client_id, status,
                          timestamp) {
        const listItem = document.createElement('li');
        listItem.innerText = `${new Date(timestamp * 1000).toLocaleString()}: ${client_id} - ${status}`;
        listItem.className = status === '200' ? 'success' : 'error';
        requestLog.appendChild(listItem);
    }

    async function sendRequest() {
        const client_id = clientIdSelector.value;
        const response = await fetch('/api/consume', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({client_id})
        });
        const result = await response.json();
        if (response.ok) {
            feedbackDiv.innerHTML = `Request accepted. Remaining: ${result.remaining}`;
            updateMetrics(result);
            logRequest(client_id, '200', result.timestamp);
        } else if (response.status === 429) {
            feedbackDiv.innerHTML = `Rate limit exceeded. Retry after ${result.retry_after} seconds.`;
            setTimeout(() => { feedbackDiv.innerHTML = ''; }, 2000);
        }
    }

    async function burstTraffic() {
        for (let i = 0; i < 5; i++) {
            await sendRequest();
            await new Promise(resolve => setTimeout(resolve, 100));
        }
    }

    sendRequestBtn.addEventListener('click', sendRequest);
    burstTrafficBtn.addEventListener('click', burstTraffic);

    resetBtn.addEventListener('click', async () => {
        const response = await fetch('/api/reset', { method: 'POST' });
        const result = await response.json();
        feedbackDiv.innerHTML = result.message;
        requestLog.innerHTML = '';
        updateMetrics({ total_requests: 0, accepted_requests: 0, rejected_requests: 0, rejection_rate: 0 });
    });
});