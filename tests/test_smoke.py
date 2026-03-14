"""Smoke tests verifying basic imports and fixtures."""


def test_import_enums():
    from kryptoskatt.enums import Chain, EventType, Platform

    assert Chain.ETHEREUM == "ETHEREUM"
    assert Platform.COINBASE == "COINBASE"
    assert EventType.BUY == "BUY"


def test_import_schemas():
    from kryptoskatt.schemas import K4Report, TransactionCreate

    assert TransactionCreate is not None
    assert K4Report is not None


#KW|


#HQ|


def test_import_config():
    # Settings should load without error — all fields have defaults.
    import kryptoskatt.config
    assert kryptoskatt.config.settings is not None


#HQ|

#KW|

def test_sample_buy_fixture(sample_buy_eth):
    from decimal import Decimal

    assert sample_buy_eth.base_coin == "ETH"
    assert sample_buy_eth.base_amount == Decimal("0.5")
    assert sample_buy_eth.event_type == "BUY"


def test_sample_swap_fixture(sample_swap_btc_to_eth):
    swap_out, swap_in = sample_swap_btc_to_eth
    assert swap_out.event_type == "SWAP_OUT"
    assert swap_in.event_type == "SWAP_IN"
    assert swap_out.base_coin == "BTC"
    assert swap_in.base_coin == "ETH"


def test_sample_reward_fixture(sample_reward_geod):
    assert sample_reward_geod.base_coin == "GEOD"
    assert sample_reward_geod.event_type == "REWARD"


def test_fixture_files_exist(fixtures_dir):
    assert (fixtures_dir / "coinbase_sample.csv").exists()
    assert (fixtures_dir / "crypto_com_sample.csv").exists()
    assert (fixtures_dir / "mexc_deposit_sample.tsv").exists()
    assert (fixtures_dir / "mexc_withdrawal_sample.tsv").exists()


def test_wallet_fixtures(sample_eth_wallet, sample_sol_wallet):
    assert sample_eth_wallet.chain == "ETHEREUM"
    assert sample_sol_wallet.chain == "SOLANA"
    assert sample_eth_wallet.is_mine is True
