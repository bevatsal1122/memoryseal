import stat

import pytest
from dotenv import dotenv_values
from eth_account import Account

from scripts.init_demo_wallets import create


def test_wallet_file_is_private_distinct_and_never_overwritten(tmp_path):
    path = tmp_path / "demo.env"
    addresses = create(path)
    saved = path.read_bytes()
    values = dotenv_values(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(set(addresses.values())) == 4
    for name, address in addresses.items():
        assert Account.from_key(values[f"MEMORYSEAL_DEMO_{name.upper()}_KEY"]).address == address
    with pytest.raises(FileExistsError):
        create(path)
    assert path.read_bytes() == saved
