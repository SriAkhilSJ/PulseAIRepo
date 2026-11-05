# PHASE 11.3 REMAINING LIMITATIONS & ROADMAP

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.3 Workspace Discipline & Change Management  

---

## 1. IDENTIFIED LIMITATIONS & MITIGATIONS

1. **Cross-Volume Hardlinks:** NTFS hardlinks cannot cross drive boundaries. Hardlink creation is explicitly rejected; standard atomic replacement is enforced.
2. **Network Filesystems (SMB/NFS):** On high-latency network shares, file locking may encounter transient delays. The broker uses bounded re-tries with backoff.
3. **Very Large Binary Baselines:** Fingerprinting gigabyte-sized binary files during baseline capture is mitigated by skipping standard build/cache directories (`.git`, `node_modules`, `.venv`, `dist`, `build`).
