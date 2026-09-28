// Deploys EnergyLedger and writes deployments/<network>.json (address, ABI,
// deployer, block). The backend reads that file, so after a deploy no manual
// copying of the address/ABI is needed.
//   local:   npm run node   (separate terminal)  then  npm run deploy:local
//   sepolia: set SEPOLIA_RPC_URL + SEPOLIA_PRIVATE_KEY in ../.env, then npm run deploy:sepolia
const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const Ledger = await hre.ethers.getContractFactory("EnergyLedger");
  const ledger = await Ledger.deploy();
  await ledger.waitForDeployment();
  const receipt = await ledger.deploymentTransaction().wait();

  const artifact = await hre.artifacts.readArtifact("EnergyLedger");
  const net = await hre.ethers.provider.getNetwork();
  const out = {
    network: hre.network.name,
    chainId: Number(net.chainId),
    address: await ledger.getAddress(),
    deployer: deployer.address,
    blockNumber: receipt.blockNumber,
    txHash: receipt.hash,
    deployedAt: new Date().toISOString(),
    abi: artifact.abi,
  };
  const dir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${hre.network.name}.json`), JSON.stringify(out, null, 2));
  console.log(
    `EnergyLedger deployed to ${out.address} on ${out.network} (chainId ${out.chainId}), block ${out.blockNumber}`
  );
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
