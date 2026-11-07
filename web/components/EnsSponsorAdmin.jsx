"use client";
import {useState} from 'react';
import ActionNotice from './ActionNotice';
import {configureSponsor} from '../lib/ens-sponsor-admin.mjs';
export default function EnsSponsorAdmin({account,request}){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[status,setStatus]=useState('');
 return <details className="detail"><summary>ENS operator setup</summary>
  <p>One-time setup for the owner of memoryseal.eth. Deploys its subregistry and authorizes the backend registrar. Other users do not need this step.</p>
  <ActionNotice message={error} onClose={()=>setError('')}/>
  <button disabled={busy} onClick={async()=>{setBusy(true);setError('');try{
   const config=await request(account,'GET','/ens-registration/config');
   if(!config.registrar)throw Error('Configure the dedicated registrar key on Railway first.');
   const key=`memoryseal:sponsor-admin:${account}:${config.parent}:${config.registrar}`;
   const job=JSON.parse(localStorage.getItem(key)||'null')||{salt:BigInt('0x'+crypto.randomUUID().replaceAll('-','')).toString()};
   const save=value=>localStorage.setItem(key,JSON.stringify(value));save(job);
   const registry=await configureSponsor(window.ethereum,account,config,job,save,setStatus);
   setStatus(`Ready. Registry: ${registry}`);
  }catch(e){setError(e.shortMessage||e.message);}finally{setBusy(false);}}}>{busy?'Confirm setup in wallet…':'Configure sponsored registration'}</button>
  {status&&<p role="status">{status}</p>}
 </details>;
}
