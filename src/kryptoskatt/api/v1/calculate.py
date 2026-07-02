"""Calculate endpoint for API v1."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kryptoskatt.api.schemas import (
    CalculateRequest,
    CalculateResponse,
    DedupSummary,
    EnrichmentSummary,
    TransferSummary,
)
from kryptoskatt.db import get_db
from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.engine.price_enrichment import PriceEnrichmentEngine
from kryptoskatt.engine.transfers import TransferMatcher
from kryptoskatt.models.account import Account
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


@router.post("/calculate", response_model=CalculateResponse)
def calculate(
    body: CalculateRequest,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    uid = account.id

    dedup = DeduplicationEngine(db, uid)
    dedup_report = dedup.deduplicate_all()

    enrichment = PriceEnrichmentEngine(db, uid)
    enrich_report = enrichment.enrich()

    wallet_service = WalletService(db, uid)
    my_addresses = wallet_service.get_my_addresses()
    matcher = TransferMatcher(db, my_addresses, uid)
    transfer_report = matcher.match_all()

    gav = GavEngine(db, uid)
    result = gav.calculate(year=body.year)

    return CalculateResponse(
        disposals_created=len(result.disposals),
        gav_entries_created=len(result.gav_ledger_entries),
        dedup_report=DedupSummary(
            total_checked=dedup_report.total_checked,
            exact_matches=dedup_report.exact_matches,
            heuristic_matches=dedup_report.heuristic_matches,
        ),
        transfer_report=TransferSummary(
            matched=transfer_report.matched,
            unmatched=transfer_report.unmatched,
            ambiguous=transfer_report.ambiguous,
        ),
        enrichment_report=EnrichmentSummary(
            total=enrich_report.total,
            enriched=enrich_report.enriched,
            skipped_unknown_coin=enrich_report.skipped_unknown_coin,
            skipped_api_miss=enrich_report.skipped_api_miss,
        ),
        warnings=result.warnings,
    )
