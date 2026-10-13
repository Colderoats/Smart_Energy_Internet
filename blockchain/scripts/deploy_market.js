// Deploys EnergyMarket (paper trading contract) and writes deployments/market.<network>.json.
// The gateway/oracle account defaults to the SECOND signer (a dev account); set MARKET_GATEWAY to override.
//   npm run node   (separate terminal)   then   npm run deploy:market
// EnergyLedger and its deploy script are untouched.
const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

async function main() {
  const [deployer, defaultGateway] = await hre.ethers.getSigners();
  const gateway = process.env.MARKET_GATEWAY || defaultGateway.address;
  const Market = await hre.ethers.getContractFactory("EnergyMarket");
  const market = await Market.deploy(gateway);
  await market.waitForDeployment();
  const receipt = await market.deploymentTransaction().wait();
  const artifact = await hre.artifacts.readArtifact("EnergyMarket");
  const net = await hre.ethers.provider.getNetwork();
  const out = {
    network: hre.network.name,
    chainId: Number(net.chainId),
    address: await market.getAddress(),
    deployer: deployer.address,
    gateway,
    blockNumber: receipt.blockNumber,
    txHash: receipt.hash,
    deployedAt: new Date().toISOString(),
    abi: artifact.abi,
  };
  const dir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `market.${hre.network.name}.json`), JSON.stringify(out, null, 2));
  console.log(`EnergyMarket deployed to ${out.address} on ${out.network} (gateway ${gateway})`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
