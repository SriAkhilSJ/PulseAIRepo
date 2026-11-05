# PHASE 10.0 KNOWN LIMITATIONS & FUTURE WORK

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 10.0 Identity & RBAC  

---

1. **Hardware Security Modules (HSM):**
   Signing keys are currently managed in-memory with optional environment variable injection; future enterprise deployments should support PKCS#11 or AWS KMS / Azure Key Vault backends.
2. **SAML 2.0 Identity Federation:**
   Authentication currently supports OAuth 2.0 / OIDC and salted PBKDF2 local credentials; enterprise SAML 2.0 XML assertion parsing is scheduled for a future release.
3. **Attribute-Based Access Control (ABAC):**
   Current authorization is role-based (RBAC) with contextual scoping (org, workspace, project, risk tier); full dynamic ABAC policy expressions (e.g. OPA / Rego) can be added incrementally.
