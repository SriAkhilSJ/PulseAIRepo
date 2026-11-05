# PHASE 10.0 SESSION MANAGEMENT REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Module:** `src/identity/auth.py`  

---

## 1. REFRESH TOKEN ROTATION & REPLAY DEFENSE

Sessions implement single-use refresh token rotation:
1. Upon login, an access token (1 hour TTL) and a composite refresh token (`session_id.secret`) are issued.
2. The refresh secret is stored exclusively as a SHA-256 hash.
3. Presenting a refresh token invalidates the old secret, issues a new token pair, and writes a new hashed secret.
4. **Replay Detection:** If an already-rotated or invalid refresh token is submitted, the session is immediately marked `is_revoked = True` and all active tokens are revoked.

## 2. SESSION REVOCATION
- Individual session revocation via `revoke_session(session_id)`.
- User-wide revocation across all devices via `revoke_all_user_sessions(user_id)`.
