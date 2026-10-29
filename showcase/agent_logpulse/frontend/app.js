const logOutput = document.getElementById('logOutput');
const levelFilter = document.getElementById('levelFilter');
const searchInput = document.getElementById('searchInput');
const applyFiltersButton = document.getElementById('applyFilters');
const logForm = document.getElementById('logForm');
const pauseResumeButton = document.getElementById('pauseResume');

let autoScroll = true;
let paused = false;

const toggleAutoScroll = () => {
    autoScroll = !autoScroll;
    toggleAutoScroll.textContent = autoScroll ? 'Disable Auto Scroll' : 'Enable Auto Scroll';
};

toggleAutoScrollButton.addEventListener('click', toggleAutoScroll);

const fetchStats = async () => {
    const response = await fetch('/api/stats');
    const stats = await response.json();
    document.getElementById('totalLogs').innerText = stats.total;
    document.getElementById('errorRate').innerText = stats.error_rate.toFixed(2) + '%';
};

const streamLogs = async () => {
    const eventSource = new EventSource('/api/stream');
    eventSource.onmessage = function(event) {
        if (!paused) {
            logOutput.value += event.data + '\n';
            if (autoScroll) {
                logOutput.scrollTop = logOutput.scrollHeight;
            }
        }
    };
};

logForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const logSource = document.getElementById('logSource').value;
    const logLevel = document.getElementById('logLevel').value;
    const logMessage = document.getElementById('logMessage').value;

    await fetch('/api/logs', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ level: logLevel, message: logMessage, source: logSource, timestamp: new Date().toISOString() })
    });
    logForm.reset();
});

applyFiltersButton.addEventListener('click', async () => {
    const level = levelFilter.value;
    const search = searchInput.value;
    const response = await fetch(`/api/logs?level=${level}&search=${search}`);
    const logs = await response.json();
    logOutput.value = logs.map(log => `${log.level} - ${log.message} (${log.source})`).join('\n');
});

streamLogs();
fetchStats();
setInterval(fetchStats, 10000); // Fetch stats every 10 seconds
