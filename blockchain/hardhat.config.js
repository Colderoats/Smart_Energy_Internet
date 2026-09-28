// Module 5 - Hardhat config.
// Default: in-process Hardhat network for tests, `localhost` for the local
// dev node (`npm run node`). Sepolia is ready to switch on via env vars
// (SEPOLIA_RPC_URL, SEPOLIA_PRIVATE_KEY) in the repo-root .env; it is only
// registered when both are set, so local work never needs them.
require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: require("path").resolve(__dirname, "..", ".env") });

const { SEPOLIA_RPC_URL, SEPOLIA_PRIVATE_KEY } = process.env;

const networks = {
  localhost: { url: "http://127.0.0.1:8545" },
};
if (SEPOLIA_RPC_URL && SEPOLIA_PRIVATE_KEY) {
  networks.sepolia = {
    url: SEPOLIA_RPC_URL,
    accounts: [SEPOLIA_PRIVATE_KEY.startsWith("0x") ? SEPOLIA_PRIVATE_KEY : `0x${SEPOLIA_PRIVATE_KEY}`],
    chainId: 11155111,
  };
}

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: { optimizer: { enabled: true, runs: 200 } },
  },
  networks,
};
