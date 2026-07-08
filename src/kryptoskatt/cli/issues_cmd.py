"""CLI issues command for displaying flagged issues."""

from kryptoskatt.db import get_session
from kryptoskatt.reports.issues import FlaggedIssuesGenerator
from kryptoskatt.services.auth import get_legacy_user_id


def run_issues(year: int) -> None:
    """Run the issues command to check for flagged issues.

    Args:
        year: Tax year to check for issues.
    """
    session = get_session()
    try:
        generator = FlaggedIssuesGenerator(session, get_legacy_user_id(session))
        report = generator.generate(year=year)

        if not report.issues:
            print(f"Inga problem hittades för år {year}")
            return

        print(f"\nFlaggade problem för {year}:")
        print(f"  Fel: {report.total_errors}")
        print(f"  Varningar: {report.total_warnings}")
        print(f"  Info: {report.total_info}")
        print()

        for issue in report.issues:
            severity_symbol = {"ERROR": "❌", "WARNING": "⚠️", "INFO": "ℹ️"}[issue.severity]
            print(f"{severity_symbol} [{issue.severity}] {issue.category}")
            print(
                f"   {issue.coin}: {issue.amount} @ {issue.timestamp_utc.strftime('%Y-%m-%d %H:%M')}"
            )
            print(f"   {issue.description}")
            print()
    finally:
        session.close()
