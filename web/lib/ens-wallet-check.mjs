export async function checkEnsWallet(wallet, owner) {
  if (!wallet?.request) throw new Error('Connect your wallet to MemorySeal first.');
  const [chain, accounts] = await Promise.all([
    wallet.request({method:'eth_chainId'}), wallet.request({method:'eth_accounts'}),
  ]);
  if (Number(chain) !== 11155111) {
    const error = new Error(`MemorySeal’s wallet connection is on chain ${Number(chain)}, not Sepolia. Click “Switch wallet to Sepolia”, then reconnect if prompted and retry setup.`);
    error.code = 'ENS_WRONG_NETWORK';
    throw error;
  }
  if (!accounts.some(address => address.toLowerCase() === owner.toLowerCase())) {
    throw new Error(`MemorySeal is signed in as ${owner}, but that account is not connected in the wallet. Use Switch account to reconnect the parent owner.`);
  }
}

export async function switchEnsNetwork(wallet) {
  await wallet.request({method:'wallet_switchEthereumChain', params:[{chainId:'0xaa36a7'}]});
}
