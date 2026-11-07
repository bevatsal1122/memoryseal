import {assertLocalRequest, walletStatus} from '../../../../lib/sepolia-demo-server.mjs';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function GET(request) {
 try {assertLocalRequest(request);return Response.json(await walletStatus(),{headers:{'Cache-Control':'no-store'}});}
 catch(error){return Response.json({error:error.message},{status:400});}
}
