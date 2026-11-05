# CRUSOR AI IDE — PHASE 9.6: KNOWN LIMITATIONS & FUTURE WORK

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Parent Phase:** 9.5  
**Verdict:** `DESKTOP PERFORMANCE AND OBSERVABILITY VERIFIED`  

---

## 1. KNOWN ARCHITECTURAL LIMITATIONS

1. **Cross-Platform OS Process Isolation:**
   - Windows AppContainer and Job Objects are fully implemented and verified for Windows 10/11 x64.
   - Linux (cgroups/namespaces) and macOS (`sandbox-exec`) require corresponding platform-specific sandbox daemons before enterprise deployment on those OS targets.
2. **Local Tokenizer Memory:**
   - In-memory local tokenizers for large models (e.g. 128k context vocabularies) consume ~65 MB RSS in the Python sidecar. This is within budget but can be further reduced via mmap-backed tokenizers.
3. **Headless Browser Cold Launch:**
   - Cold startup of headless Chromium via Playwright takes ~620 ms. While within the 1-second budget, warm browser pooling could reduce this to < 100 ms for active web testing workflows.
