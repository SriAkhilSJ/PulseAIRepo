# PHASE 9.4.2 — NETWORK BOUNDARY EVIDENCE REPORT

**Phase:** 9.4.2 (Windows Filesystem & Network Isolation)  
**Platform:** Windows 10/11 x64  
**OS Subsystem:** Windows Kernel TCP/IP Driver (`tcpip.sys`) & Ancillary Function Driver for WinSock (`afd.sys`)  
**Audit Date:** November 4, 2026  
**Status:** **KERNEL-ENFORCED NETWORK ISOLATION VERIFIED**

---

## 1. EMPIRICAL NETWORK TEST MATRIX

The table below summarizes empirical network test vectors executed against the AppContainer worker.

| Test ID | Operation Vector | Protocol / Port | Target Destination | Expected OS Behavior | Observed Outcome | OS Error Code / Exception |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **NET-01** | `socket.connect()` | TCP / 443 | `1.1.1.1` (Cloudflare) | Kernel socket connect denial | **Denied** | `WSAEACCES: [WinError 10013]` |
| **NET-02** | `socket.connect()` | TCP / 53 | `8.8.8.8` (Google DNS) | Kernel socket connect denial | **Denied** | `WSAEACCES: [WinError 10013]` |
| **NET-03** | `socket.connect()` | TCP / 80 | `127.0.0.1` (Host Localhost) | Blocked without loopback capability | **Denied** | `TimeoutError: timed out` |
| **NET-04** | `socket.gethostbyname()`| UDP/TCP / 53 | `google.com` (Public FQDN) | Kernel DNS query resolution denial | **Denied** | `gaierror: [Errno 11001] getaddrinfo failed`|
| **NET-05** | `socket.sendto()` | UDP / 53 | `8.8.8.8` (Raw DNS Packet) | Inbound response dropped | **Denied** | `TimeoutError: timed out` |
| **NET-06** | `curl.exe` CLI | HTTPS / 443 | `https://1.1.1.1` | Kernel socket connect denial | **Denied** | `curl: (7) connect failed: Bad access` |
| **NET-07** | `curl.exe` CLI | HTTPS / 443 | `https://google.com` | DNS resolution failure | **Denied** | `curl: (6) Could not resolve host: google.com` |

---

## 2. KERNEL NETWORK ISOLATION MECHANISM

Windows AppContainer network isolation is enforced directly within the kernel drivers `afd.sys` and `tcpip.sys`, operating beneath the user-mode WinSock layer (`ws2_32.dll`):

1. **Security Capability Validation:**
   In Windows NT, networking capabilities are represented by well-known SID claims:
   - `internetClient` (`S-1-15-3-1`): Outbound Internet access.
   - `privateNetworkClientServer` (`S-1-15-3-2`): Intranet and home network access.
   - `internetClientServer` (`S-1-15-3-3`): Inbound Internet listener.

2. **Zero-Capability Provisioning (`CapabilityCount = 0`):**
   In `src/security/sandbox/windows.py`, Crusor configures `SECURITY_CAPABILITIES` with:
   ```c
   sec_caps.CapabilityCount = 0;
   sec_caps.Capabilities = NULL;
   ```
   When `WSAConnect` or `connect()` makes an I/O control request (`IOCTL_AFD_CONNECT`) to `\Device\Afd`, `afd.sys` queries the process token's capability list. Finding no network capabilities, the driver returns `STATUS_NETWORK_ACCESS_DENIED (0xC000022B)`. WinSock translates this to `WSAEACCES (10013)`:
   > *"An attempt was made to access a socket in a way forbidden by its access permissions."*

3. **DNS Query Interception:**
   Calls to `getaddrinfo()` send RPC requests to the Windows DNS Client Service (`Dnscache`). The DNS service verifies client capabilities before performing network resolution. Lacking `internetClient`, the service rejects the lookup with `WSANO_DATA` / `WSAHOST_NOT_FOUND`, surfacing to Python as `gaierror: [Errno 11001] getaddrinfo failed`.

4. **Inbound Packet Dropping:**
   Even if an asynchronous raw socket emits a packet locally, Windows Filtering Platform (WFP) packet classification filters drop all incoming reply packets directed to the AppContainer process, guaranteeing that no external data can be received.

---

## 3. VERDICT

Network isolation is **empirically verified** and enforced by the operating system kernel. Untrusted agent-generated code cannot establish outbound TCP connections, perform DNS resolution, or receive inbound UDP replies.

