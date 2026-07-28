import subprocess
import sys


TESTS = [
    # Planning / replanning
    "src.tests.test_planner_manual",
    "src.tests.test_replanner_manual",
    "src.tests.test_replan_graph",

    # Plan Mode
    "src.tests.test_plan_mode",
    "src.tests.test_plan_approval",
    "src.tests.test_plan_revision",
    "src.tests.test_plan_cancel",

    # Recovery
    "src.tests.test_keep_recovery",
    "src.tests.test_replan_recovery",
]

def run_test(module: str) -> bool:
    print("\n" + "=" * 70)
    print(f"RUNNING: {module}")
    print("=" * 70)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            module,
        ],
        text=True,
    )

    if result.returncode == 0:
        print(f"\n[PASS] {module}")
        return True

    print(
        f"\n[FAIL] {module} "
        f"(exit code {result.returncode})"
    )
    return False


def main():
    passed = []
    failed = []

    for module in TESTS:
        if run_test(module):
            passed.append(module)
        else:
            failed.append(module)

    print("\n" + "=" * 70)
    print("PULSECODEAI REGRESSION RESULTS")
    print("=" * 70)

    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failed)}")
    print(f"Total:  {len(TESTS)}")

    if failed:
        print("\nFAILED TESTS:")

        for module in failed:
            print(f"- {module}")

        raise SystemExit(1)

    print("\nALL REGRESSION TESTS PASSED")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
