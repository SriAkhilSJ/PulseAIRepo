import socket, threading, time, sys, os, uuid
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from src.security import ExecutionBroker, ExecutionRequest, ExecutionMode

broker = ExecutionBroker.get_instance()
ws = str((repo_root / "bench-results" / "test_ac_perm").resolve())

tcp6_received = []
def run_tcp6():
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('::1', 45682))
        s.listen(5)
        s.settimeout(3.0)
        conn, addr = s.accept()
        data = conn.recv(1024)
        tcp6_received.append((addr, data))
        conn.sendall(b'ACK6')
        conn.close()
        s.close()
    except Exception as e:
        tcp6_received.append(('EXCEPTION', str(e)))

udp6_received = []
def run_udp6():
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.bind(('::1', 45683))
        s.settimeout(3.0)
        while True:
            data, addr = s.recvfrom(1024)
            udp6_received.append((addr, data))
    except Exception as e:
        pass

t_tcp6 = threading.Thread(target=run_tcp6, daemon=True)
t_udp6 = threading.Thread(target=run_udp6, daemon=True)
t_tcp6.start()
t_udp6.start()
time.sleep(0.3)

worker_code = """
import socket

print("=== WORKER IPV6 ATTEMPTS ===")
# 1. TCP IPv6 Loopback
try:
    s_tcp = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s_tcp.settimeout(1.0)
    s_tcp.connect(('::1', 45682))
    s_tcp.sendall(b'LEAK_TCP6_APPCONTAINER')
    print('TCP6_CONNECT:SUCCESS')
    s_tcp.close()
except Exception as e:
    print(f'TCP6_CONNECT:DENIED:{type(e).__name__}:{e}')

# 2. UDP IPv6 Loopback
try:
    s_udp = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    s_udp.settimeout(1.0)
    res = s_udp.sendto(b'LEAK_UDP6_APPCONTAINER', ('::1', 45683))
    print(f'UDP6_SENDTO:CALLED:{res}')
    s_udp.close()
except Exception as e:
    print(f'UDP6_SENDTO:DENIED:{type(e).__name__}:{e}')
"""

token = broker.create_approval("s_net6_proof", "r_net6_proof", "python net6_test", ws)
req = ExecutionRequest(
    execution_id=str(uuid.uuid4()),
    session_id="s_net6_proof",
    request_id="r_net6_proof",
    workspace_root=ws,
    mode=ExecutionMode.READ_ONLY,
    tool_name="terminal",
    command="python net6_test",
    argv=[sys.executable, "-c", worker_code],
    approval_token=token,
)

rec = broker.execute(req)
print("Worker stdout:\n", rec.stdout.strip())
time.sleep(0.5)
print("Host TCP6 Receiver observed:", tcp6_received)
print("Host UDP6 Receiver observed:", udp6_received)
