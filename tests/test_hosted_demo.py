import pytest
from fastapi import HTTPException
from memoryseal.demo import hosted

OPERATOR = '0x2135bc4f6a38b000a7217662f92d3978a50c5696'


def configured(monkeypatch, tmp_path):
    values = {
        'MEMORYSEAL_DEMO_ENABLED': 'true',
        'MEMORYSEAL_DEMO_OPERATORS': OPERATOR,
        'MEMORYSEAL_DEMO_PRIVATE_KEY': 'test-placeholder',
        'MEMORYSEAL_DEMO_RECIPIENT': OPERATOR,
        'MEMORYSEAL_DEMO_DATA_DIR': str(tmp_path / 'demo'),
        'MEMORYSEAL_DEMO_FRONTEND_ORIGIN': 'https://memoryseal.work',
        'RAILWAY_VOLUME_MOUNT_PATH': str(tmp_path),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_hosted_demo_disabled_by_default(monkeypatch):
    monkeypatch.delenv('MEMORYSEAL_DEMO_ENABLED', raising=False)
    with pytest.raises(HTTPException) as error:
        hosted.authorize_operator(OPERATOR)
    assert error.value.status_code == 503


def test_hosted_demo_rejects_other_wallet_before_configuration(monkeypatch, tmp_path):
    configured(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as error:
        hosted.authorize_operator('0x' + '1' * 40)
    assert error.value.status_code == 403


def test_hosted_demo_accepts_only_configured_operator(monkeypatch, tmp_path):
    configured(monkeypatch, tmp_path)
    hosted.authorize_operator(OPERATOR.upper())


def test_hosted_demo_requires_persistent_journal(monkeypatch, tmp_path):
    configured(monkeypatch, tmp_path)
    monkeypatch.setenv('MEMORYSEAL_DEMO_DATA_DIR', '/tmp/demo')
    with pytest.raises(HTTPException, match='persistent'):
        hosted.authorize_operator(OPERATOR)


def test_hosted_demo_requires_https_source(monkeypatch, tmp_path):
    configured(monkeypatch, tmp_path)
    monkeypatch.setenv('MEMORYSEAL_DEMO_FRONTEND_ORIGIN', 'http://example.com')
    with pytest.raises(HTTPException, match='HTTPS'):
        hosted.authorize_operator(OPERATOR)


def test_worker_only_calls_internal_gateway(monkeypatch):
    monkeypatch.setenv('PORT', '8123')
    monkeypatch.setenv('MEMORYSEAL_DEMO_GATEWAY_URL', 'https://untrusted.example')
    assert hosted.worker_env()['MEMORYSEAL_DEMO_GATEWAY_URL'] == 'http://127.0.0.1:8123'
