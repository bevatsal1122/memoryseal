from memoryseal.config import Settings


def test_dotenv_accepts_optional_empty_values_and_hides_arkiv_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "MEMORYSEAL_ONCHAIN_CHAIN_ID=\nMEMORYSEAL_ARKIV_PRIVATE_KEY=test-secret\n"
        "MEMORYSEAL_DEPLOYER_KEY=not-a-gateway-setting\n"
    )
    settings = Settings(_env_file=path)
    assert settings.onchain_chain_id is None
    assert settings.arkiv_private_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)
