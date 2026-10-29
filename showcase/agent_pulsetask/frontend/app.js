const apiUrl = 'http://localhost:5000/api';

document.getElementById('taskForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const title = document.getElementById('title').value;
    const status = document.getElementById('status').value;
    await fetch(`${apiUrl}/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, status })
    });
    document.getElementById('title').value = '';
    loadTasks();
});

async function loadTasks() {
    const response = await fetch(`${apiUrl}/tasks`);
    const tasks = await response.json();
    const taskBoard = document.getElementById('taskBoard');
    taskBoard.innerHTML = '';
    tasks.forEach(task => {
        const taskDiv = document.createElement('div');
        taskDiv.textContent = `${task.title} - ${task.status}`;
        taskBoard.appendChild(taskDiv);
    });
}

async function loadStats() {
    const response = await fetch(`${apiUrl}/stats`);
    const stats = await response.json();
    document.getElementById('total').textContent = `Total: ${stats.total}`;
    document.getElementById('todo').textContent = `Todo: ${stats.todo}`;
    document.getElementById('doing').textContent = `Doing: ${stats.doing}`;
    document.getElementById('done').textContent = `Done: ${stats.done}`;
}

loadTasks();
loadStats();