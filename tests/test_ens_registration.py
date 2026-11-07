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
