# CRUSOR AI IDE — PHASE 9.6: UPSTREAM INVARIANT 7 VERIFICATION REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Upstream Repository:** `https://github.com/microsoft/vscode`  
**Upstream Pin Commit:** `6c27443ce6fdf6ac798c64025d45175e2e23c4b4`  
**Verification Script:** `python scripts/refresh_selective_manifest.py`  
**Verdict:** `UPSTREAM INVARIANT 7 VERIFIED — ZERO DRIFT`  

---

## 1. PERMITTED UPSTREAM MODIFIED FILES (EXACTLY 5)

| Index | File Path | Upstream SHA-256 | Overlay SHA-256 | Status |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `build/buildfile.ts` | `aa6bba8088e65560583c8426c609cc4b76f8910b1f52e210fed48d77220de9bc` | `bca01aa1b2942cfdb2b79298812131f32f37525c1ccf530816e22e82bae15a47` | **PERMITTED** |
| 2 | `build/next/index.ts` | `4e2b3a122788f4dd5dbd6b90ad764882e43caf78a927d136dcaf05836bfb27ea` | `6ea3a4875fed3e361520143800c2a34d447741ca23dc2f6d422b3af7dceb9cd8` | **PERMITTED** |
| 3 | `product.json` | `d7a5ed67fe83f7b52726e2cd62d14baf87849dd0d5263bc63814570ac8ac537f` | `c13255bd2b02e9f629632c576f5681d62c20f8d07a8b1586c31d7791f99af0f5` | **PERMITTED** |
| 4 | `src/vs/workbench/workbench.common.main.ts` | `d11142346b159434f4914d56e83b825917689f394089147a5182b8a70dbf1093` | `9179afdb335cac1dcc1b8ab8dc2c5afa24b74eb506736099c33a2b43eebedd86` | **PERMITTED** |
| 5 | `src/vs/workbench/workbench.desktop.main.ts` | `712e88e07b41b8f515e58a76ed8268df1575acbbd1aea18ff84653fb6089bc17` | `7a59061b567f71565f82def944bbe99f4d5aa60bf991330ccc3481f97d87fcf2` | **PERMITTED** |

---

## 2. DRIFT AUDIT VERIFICATION

Running `scripts/refresh_selective_manifest.py` produced:
```
desktop/SELECTIVE_MANIFEST.json: all receipts match the tree. Nothing to do.
```
No unauthorized files were modified. All new functionality resides inside first-party directories.
