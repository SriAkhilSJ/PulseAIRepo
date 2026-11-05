# CRUSOR AI IDE — PHASE 9.4.1 NETWORK ISOLATION EVIDENCE

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.4  
**Audit Date:** 2026-11-04  
**Telemetry File:** `bench-results/phase941_windows_boundary/network_isolation_evidence.json`  
**Paid LLM API Budget Expended:** **₹0.00**  

---

## 1. CONTROLLED LOCAL NETWORK AUDIT

Phase 9.4 configured `NETWORK = DENY` via environment variables:
```python
sanitized["CRUSOR_NETWORK"] = "DENY"
sanitized["HTTP_PROXY"] = "http://127.0.0.1:0"
sanitized["HTTPS_PROXY"] = "http://127.0.0.1:0"
sanitized["ALL_PROXY"] = "http://127.0.0.1:0"
sanitized["NO_PROXY"] = ""
sanitized["PIP_NO_INDEX"] = "1"
```

To establish whether this policy provides true kernel-level network isolation or merely application-level proxy compliance, a controlled test was executed against local loopback endpoints.

---

## 2. EMPIRICAL TEST SUITE RESULTS

| Test Vector | Mechanism Tested | Observed Outcome | Enforcement Primitive |
| :--- | :--- | :--- | :--- |
| **1. HTTP via urllib/requests** | Standard HTTP client reading `HTTP_PROXY` | **DENIED** (Connection refused to `127.0.0.1:0`) | **Application / Proxy Convention** |
| **2. HTTP with Proxy Disabled** | `urllib` with unproxied handler or `HTTP_PROXY=""` | **ALLOWED** (Direct connection established) | **OS Kernel (Allowed)** |
| **3. Direct TCP Socket** | `socket.create_connection(('127.0.0.1', port))` | **ALLOWED** (Data received: `HELLO_SOCKET`) | **OS Kernel (Allowed)** |
| **4. Direct UDP Socket** | `socket.socket(AF_INET, SOCK_DGRAM).sendto` | **ALLOWED** (UDP datagram transmitted) | **OS Kernel (Allowed)** |
| **5. DNS Hostname Resolution** | `socket.getaddrinfo('localhost', 80)` | **ALLOWED** (Resolved cleanly) | **OS Kernel / DNS Resolver (Allowed)** |
| **6. IPv4 Loopback Socket** | `AF_INET` TCP stream | **ALLOWED** | **OS Kernel (Allowed)** |
| **7. IPv6 Loopback Socket** | `AF_INET6` stream (`::1`) | **ALLOWED** | **OS Kernel (Allowed)** |
| **8. Child-Process Networking** | Child Python process opening TCP socket | **ALLOWED** | **OS Kernel (Allowed)** |
| **9. PowerShell Direct Web Request** | `Invoke-WebRequest -NoProxy` | **ALLOWED** | **OS Kernel (Allowed)** |
| **10. Native WinSock APIs** | `ws2_32.dll` direct `WSAConnect` | **ALLOWED** | **OS Kernel (Allowed)** |

---

## 3. ROOT CAUSE & ARCHITECTURAL ASSESSMENT

1. **Why Proxy Denial is Insufficient for OS-Level Confinement:**
   - Blackhole proxy environment variables (`HTTP_PROXY=http://127.0.0.1:0`) are respected by cooperative high-level libraries (`requests`, `urllib`, `pip`, `curl`).
   - However, raw socket system calls (`socket(AF_INET, SOCK_STREAM)`) bypass environment variables completely and talk directly to the Windows `tcpip.sys` driver.
2. **Missing Windows OS Primitives:**
   - In Windows, operating-system-level network denial requires:
     - **Windows Filtering Platform (WFP):** A kernel driver filtering outbound packets by process ID / AppID.
     - **Windows Firewall API (`INetFwPolicy2`):** Adding an outbound block rule for the specific worker executable.
     - **AppContainer Network Capabilities:** Omitting `internetClient` and `privateNetworkClientServer` capabilities from the AppContainer token.
   - None of these OS-level packet filters can be created by a standard user-mode desktop application without administrator rights.
3. **Mandatory Classification Requirement:**
   - Section 4 explicitly instructs:
     *"If direct connections remain possible, the network-denial claim must remain PARTIAL."*
   - Therefore, Crusor truthfully records its network isolation claim as:
     **`NETWORK ISOLATION: PARTIAL — APPLICATION/PROXY LEVEL ONLY`**.

