"""
run_all.py
Run the full research pipeline end-to-end.

Usage:
  python scripts/run_all.py
  python scripts/run_all.py --skip-fetch   # skip data download
"""

import sys, subprocess, argparse
from pathlib import Path


def run(cmd, cwd=None):
    print(f"\n{'='*60}")
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"[FAIL] exited {result.returncode}")
        sys.exit(result.returncode)
    print(f"[OK]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent.resolve()
    scripts   = repo_root / "scripts"

    print("="*60)
    print(" SwingResearch — Full Pipeline")
    print("="*60)

    # 1. Fetch data
    if not args.skip_fetch:
        run(f"python scripts/fetch_data.py --tickers SPY QQQ IWM "
            f"--start 2019-01-01 --end 2024-12-31", cwd=repo_root)
        run(f"python scripts/compute_indicators.py", cwd=repo_root)
    else:
        print("\n[SKIP] Data fetch")

    # 2. Backtest
    run("python scripts/backtest_vbt.py", cwd=repo_root)
    run("python scripts/backtest_simple.py", cwd=repo_root)

    # 3. QuantStats report
    run("python scripts/report_quantstats.py", cwd=repo_root)

    print("\n" + "="*60)
    print(" Pipeline complete. See reports/performance.html")
    print("="*60)


if __name__ == "__main__":
    main()
