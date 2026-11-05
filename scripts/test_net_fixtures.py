import socket, threading, time, sys
from pathlib import Path

# 1. Start a host TCP listener on 127.0.0.1
tcp_received = []
def tcp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 45678))
    s.listen(5)
    s.settimeout(3.0)
    try:
        conn, addr = s.accept()
        data = conn.recv(1024)
        tcp_received.append((addr, data))
        conn.sendall(b'HOST_TCP_ACK')
        conn.close()
    except Exception as e:
        tcp_received.append(('ERROR', str(e)))
    finally:
        s.close()

# 2. Start a host UDP listener on 127.0.0.1
udp_received = []
def udp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 45679))
    s.settimeout(3.0)
    try:
        data, addr = s.recvfrom(1024)
        udp_received.append((addr, data))
    except Exception as e:
        udp_received.append(('ERROR', str(e)))
    finally:
        s.close()

t_tcp = threading.Thread(target=tcp_server, daemon=True)
t_udp = threading.Thread(target=udp_server, daemon=True)
t_tcp.start()
t_udp.start()
time.sleep(0.2)

# Verify host can connect and send
print('Testing host to host TCP connection:')
s_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s_tcp.connect(('127.0.0.1', 45678))
s_tcp.sendall(b'HOST_HELLO_TCP')
resp = s_tcp.recv(1024)
print('Host TCP received:', resp)
s_tcp.close()

print('Testing host to host UDP send:')
s_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s_udp.sendto(b'HOST_HELLO_UDP', ('127.0.0.1', 45679))
s_udp.close()

time.sleep(0.5)
print('TCP Server state:', tcp_received)
print('UDP Server state:', udp_received)

