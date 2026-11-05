import os
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ws = REPO_ROOT / "bench-results" / "phase9342_workspace"
ws.mkdir(parents=True, exist_ok=True)

calc_ts = """export class Calculator {
    add(a: number, b: number): number {
        return a + b;
    }

    multiply(a: number, b: number): number {
        return a * b;
    }
}
"""
(ws / "calculator.ts").write_text(calc_ts, encoding="utf-8")

auth_ts = """export function authenticate(user: string, token: string): boolean {
    if (!user || !token) {
        return false;
    }
    return token.startsWith('crusor-');
}
"""
(ws / "auth.ts").write_text(auth_ts, encoding="utf-8")

test_ts = """import { Calculator } from './calculator';

export function testCalculator() {
    const calc = new Calculator();
    if (calc.add(2, 3) !== 5) {
        throw new Error('add failed');
    }
}
"""
(ws / "calculator.test.ts").write_text(test_ts, encoding="utf-8")

env_file = "SECRET_API_KEY=crusor_test_key_12345\nDATABASE_URL=postgres://localhost:5432/db\n"
(ws / ".env").write_text(env_file, encoding="utf-8")

cred_file = json.dumps({"client_id": "crusor_id", "client_secret": "super_secret_token"}, indent=2)
(ws / "credentials.json").write_text(cred_file, encoding="utf-8")

print(f"Created workspace files at: {ws}")

