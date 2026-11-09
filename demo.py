"""Run both reference agents over the SYNTHETIC dataset, print metrics, write sample_report.md."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from finpilot_eval.dataset import load_dataset  # noqa: E402
from finpilot_eval.report import build_results, render_table, write_report  # noqa: E402


def main():
    dataset = load_dataset()
    results = build_results(dataset)
    print("Finpilot agent reliability eval - SYNTHETIC data, %d documents" % len(dataset.truth))
    print()
    print(render_table(results))
    write_report(HERE / "sample_report.md", results, dataset)
    print()
    print("Wrote", HERE / "sample_report.md")


if __name__ == "__main__":
    main()
