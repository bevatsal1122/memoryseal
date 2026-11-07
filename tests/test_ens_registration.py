import json
from uuid import uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from memoryseal.db import Base
from memoryseal.models import Agent, EnsRegistrationJob
from memoryseal.config import settings
from memoryseal.ens_registration import enqueue, tick, public_status

@pytest.fixture
def queue(tmp_path, monkeypatch):
    engine=create_engine(f'sqlite:///{tmp_path}/test.db');Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    for key,value in dict(ens_auto_register=True,ens_registrar_private_key=SecretStr('test'),ens_network='sepolia',ens_rpc_url='test').items():monkeypatch.setattr(settings,key,value)
    with sessions() as db:
        a=Agent(id=str(uuid4()),owner_address='0x'+'1'*40,signing_address='0x'+'2'*40,label='Research')
        db.add(a);db.flush();enqueue(db,a);db.commit()
    return sessions

def test_quota_names_and_private_status(queue,monkeypatch):
    with queue() as db:
        row=db.scalar(select(EnsRegistrationJob));assert row.name.startswith('research-');assert row.name.endswith('.memoryseal.eth')
        assert db.get(Agent,row.agent_id).ens_name is None
        assert 'signed_transaction' not in public_status(row)
        monkeypatch.setattr(settings,'ens_registration_per_owner_day',1)
        a=Agent(id=str(uuid4()),owner_address=row.owner_address,signing_address='0x'+'3'*40)
        db.add(a);db.flush()
        with pytest.raises(HTTPException) as error:enqueue(db,a)
        assert error.value.status_code==429

def test_crash_after_prepare_reuses_exact_signed_bytes(queue):
    prepares=[];broadcasts=[]
    def call(action,**payload):
        if action=='prepare':
            prepares.append(payload['job']['stage']);return {'raw':'0x1234','hash':'0x'+'a'*64,'result':{'transactionHash':'0x'+'a'*64}}
        if action=='broadcast':
            # This read proves signed bytes are committed before broadcasting.
            with queue() as db:assert db.scalar(select(EnsRegistrationJob)).signed_transaction=='0x1234'
            broadcasts.append(payload)
            if len(broadcasts)==1:raise TimeoutError()
            return {'state':'confirmed'}
        return {'verified':True}
    tick(queue,call=call,now=100)
    tick(queue,call=call,now=1000)
    assert prepares==[0];assert broadcasts[0]==broadcasts[1]
    for now in (2000,3000,4000):tick(queue,call=call,now=now)
    with queue() as db:
        row=db.scalar(select(EnsRegistrationJob));assert row.state=='registered';assert db.get(Agent,row.agent_id).ens_name==row.name
    assert prepares==[0,1,2,3]

def test_revert_stops_and_revocation_cancels(queue):
    def call(action,**payload):
        if action=='prepare':return {'raw':'0x12','hash':'0x'+'b'*64,'result':{'transactionHash':'0x'+'b'*64}}
        return {'state':'reverted'}
    tick(queue,call=call,now=100)
    with queue() as db:assert db.scalar(select(EnsRegistrationJob)).state=='failed'

def test_revoked_unsubmitted_job_does_not_spend(queue):
    with queue() as db:
        row=db.scalar(select(EnsRegistrationJob));db.get(Agent,row.agent_id).revoked=True;db.commit()
    tick(queue,call=lambda *a,**kw:pytest.fail('must not submit'),now=100)
    with queue() as db:assert db.scalar(select(EnsRegistrationJob)).state=='cancelled'

def test_signed_setup_enqueues_once_and_ignores_claimed_ens_name(queue):
    from fastapi.testclient import TestClient
    from memoryseal.api import app
    from memoryseal.auth import authenticate
    from memoryseal.db import get_session
    owner='0x'+'4'*40
    def db_session():
        with queue() as db:yield db
    old=dict(app.dependency_overrides)
    app.dependency_overrides[get_session]=db_session
    app.dependency_overrides[authenticate]=lambda:owner
    try:
        client=TestClient(app)
        body={'request_id':str(uuid4()),'signing_address':'0x'+'5'*40,'label':'Research',
              'ens_name':'someone-elses.eth','namespace':'research','operations':['read','write'],
              'acceptance':'strict','policy_version':0,'sponsored_ens':True}
        first=client.post('/agents/setup',json=body)
        assert first.status_code==201,first.text
        again=client.post('/agents/setup',json=body)
        assert again.status_code==201 and again.json()==first.json()
        assert first.json()['ens_registration']['state']=='queued'
        assert first.json()['ens_registration']['name'].endswith('.memoryseal.eth')
        listing=client.get('/agents').json()['agents'];assert len(listing)==1
        assert listing[0]['ens_name'] is None
        assert listing[0]['ens_registration']['state']=='queued'
        with queue() as db:
            rows=db.scalars(select(EnsRegistrationJob).where(EnsRegistrationJob.owner_address==owner)).all()
            assert len(rows)==1
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(old)

def test_short_names_retry_database_collisions(queue, monkeypatch):
    import re
    with queue() as db:
        existing=db.scalar(select(EnsRegistrationJob))
        assert re.fullmatch(r'research-\d{5}\.memoryseal\.eth',existing.name)
        suffix=int(existing.name.split('.')[0].rsplit('-',1)[1])
        alternative=10000 if suffix!=10000 else 10001
        draws=iter([suffix-10000,alternative-10000])
        monkeypatch.setattr('memoryseal.ens_registration.secrets.randbelow',lambda _:next(draws))
        a=Agent(id=str(uuid4()),owner_address='0x'+'6'*40,signing_address='0x'+'7'*40,label='Research')
        db.add(a);db.flush();row=enqueue(db,a);db.flush()
        assert row.name==f'research-{alternative}.memoryseal.eth'
        assert existing.name!=row.name

def test_onchain_collision_renames_only_unsigned_job(queue,monkeypatch):
    with queue() as db:old=db.scalar(select(EnsRegistrationJob)).name
    seen=[]
    def call(action,**payload):
        assert action=='prepare';seen.append(payload['job']['name']);return {'state':'unavailable'}
    tick(queue,call=call,now=100)
    with queue() as db:
        row=db.scalar(select(EnsRegistrationJob));assert row.name!=old
        assert json.loads(row.context_json)['name']==row.name
        assert row.signed_transaction is None and row.stage==0
    assert seen==[old]
